"""Optional, hero-local desktop renderer. No global Qt or Calibre settings.

Supplied shaders are kept verbatim in assets/ui. MIT notices remain there.
Only entry-point/uniform plumbing is adapted in memory for desktop OpenGL.
"""
from pathlib import Path
import re
import time
from calibre_plugins.manganana.presentation.choose_manga_resources import asset_root

from qt.core import QWidget, QPainter, QPixmap, Qt, QTimer, QStackedLayout, QLinearGradient, QColor
from PyQt6.QtGui import (QSurfaceFormat, QVector2D, QVector3D, QMatrix4x4,
                        QOpenGLContext, QOffscreenSurface)
try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from PyQt6.QtOpenGL import (QOpenGLShaderProgram, QOpenGLShader,
        QOpenGLFunctions_4_1_Core, QOpenGLVertexArrayObject,
        QOpenGLFramebufferObject, QOpenGLTextureBlitter)
    GL_IMPORT_ERROR = ''
except ImportError as exc:
    QOpenGLWidget = QWidget
    GL_IMPORT_ERROR = str(exc)

ASSETS = asset_root() / 'assets/ui'
SHADER = ASSETS / 'selected_work_hero.frag'
NO_SELECTION_SHADER = asset_root() / 'assets/hero_shaders/NoSelection_Shader.frag'
PALETTE = ((.231, .510, .965), (.659, .333, .969),
           (.133, .827, .933), (.957, .247, .369))
DEFAULTS = {'u_driftSpeed': .30, 'u_softness': .85, 'u_warp': .95,
            'u_heat': .7, 'u_mouseInfluence': 0.0}
# Provider shader filenames, keyed by SourceAdapter identities.
PROVIDER_PRESETS = {
    'mangadex': ASSETS / 'provider_shaders/MangaDex_Shader.frag',
    'mangapill': ASSETS / 'provider_shaders/MangaPill_Shader.frag',
    'weebcentral': ASSETS / 'provider_shaders/WeebCentral_Shader.frag',
    'mangak': ASSETS / 'provider_shaders/MangaK_Shader.frag',
    'atsu': ASSETS / 'provider_shaders/Atsu_Shader.frag',
}
VERTEX = '''#version 410 core
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}'''
HEADER = '''#version 410 core
out vec4 shaderColor;
#define gl_FragColor shaderColor
'''


def desktop_fragment(source):
    # Qt's desktop shader preamble defines highp away, leaving invalid
    # "precision float". Desktop floats already have full precision. Keep the
    # supplied on-disk source and every expression/default byte unchanged.
    body = re.sub(r'^\s*#version[^\n]*', '', source, flags=re.M)
    body = re.sub(r'\bprecision\s+(?:highp|mediump|lowp)\s+float\s*;', '', body)
    code = re.sub(r'/\*.*?\*/|//[^\n]*', '', body, flags=re.S)
    uniforms = ''
    for name, kind in (('iResolution', 'vec3'), ('iTime', 'float'), ('iMouse', 'vec4')):
        if re.search(r'\b'+name+r'\b', code) and not re.search(r'\buniform\s+\w+\s+'+name+r'\b', code):
            uniforms += f'uniform {kind} {name};\n'
    wrapper = ''
    if not re.search(r'\bvoid\s+main\s*\(', code):
        if not re.search(r'\bvoid\s+mainImage\s*\(', code):
            raise ValueError('Shader has neither main() nor mainImage()')
        wrapper = '\nvoid main() { mainImage(shaderColor, gl_FragCoord.xy); }\n'
    return HEADER + uniforms + body + wrapper


def local_format():
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    fmt.setSamples(0)
    return fmt


def context_available():
    if GL_IMPORT_ERROR:
        return False
    context = QOpenGLContext()
    context.setFormat(local_format())
    if not context.create():
        return False
    surface = QOffscreenSurface()
    surface.setFormat(context.format())
    surface.create()
    try:
        valid = surface.isValid() and context.makeCurrent(surface)
        if valid:
            context.doneCurrent()
        return bool(valid and not context.isOpenGLES() and
            (context.format().majorVersion(), context.format().minorVersion()) >= (4, 1))
    finally:
        surface.destroy()


class StaticPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap(str(ASSETS / 'selected_work_hero.png'))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_shader(self, shader):
        image = Path(shader).with_suffix('.png')
        if not image.is_file():
            image = ASSETS / 'selected_work_hero.png'
        self.pixmap = QPixmap(str(image))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self.pixmap.isNull():
            painter.drawPixmap(self.rect(), self.pixmap)


class MetadataScrim(QWidget):
    """Native readability layer; never modifies the shader or its uniforms."""
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0,0,self.width(),0)
        gradient.setColorAt(0,QColor(3,10,15,195))
        gradient.setColorAt(.65,QColor(3,10,15,190))
        gradient.setColorAt(1,QColor(3,10,15,75))
        painter.fillRect(self.rect(),gradient)


class ShaderPanel(QOpenGLWidget):
    def __init__(self, failure, shader=SHADER, parent=None):
        super().__init__(parent)
        self.setFormat(local_format())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.failure, self.shader = failure, Path(shader)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.update)
        self.fps, self.scale = 0, .5
        self.ready, self.cleaned = False, False
        self.error = ''
        self.frames = 0
        self.clock = time.perf_counter()
        self.fbo = self.program = self.vao = self.blitter = None
        self.needs_compile = True
        self.program_switches = 0
        # Bounded diagnostics; a long-running dialog cannot accumulate samples.
        self.cpu_draw_ms, self.frame_times = [], []
        self.cleanup_errors, self.gl_info = [], {}

    def fail(self, exc):
        self.error = str(exc)
        self.timer.stop()
        shader, message = self.shader, self.error
        QTimer.singleShot(0, lambda: self.failure(message) if self.shader == shader and self.error == message else None)

    def set_shader(self, shader):
        shader = Path(shader)
        if shader == self.shader:
            return
        self.shader = shader
        self.error = ''
        self.needs_compile = True
        self.clock = time.perf_counter()
        self.sync_timer()
        self.update()

    def compile_program(self):
        program = QOpenGLShaderProgram()
        for kind, source in [(QOpenGLShader.ShaderTypeBit.Vertex, VERTEX),
            (QOpenGLShader.ShaderTypeBit.Fragment, desktop_fragment(self.shader.read_text(encoding='utf-8')))]:
            if not program.addShaderFromSourceCode(kind, source):
                raise RuntimeError(program.log())
        if not program.link():
            raise RuntimeError(program.log())
        if self.program:
            self.program.removeAllShaders()
        self.program = program
        self.needs_compile = False
        self.program_switches += 1

    def initializeGL(self):
        try:
            self.context().aboutToBeDestroyed.connect(self.cleanup)
            self.funcs = QOpenGLFunctions_4_1_Core()
            if not self.funcs.initializeOpenGLFunctions():
                raise RuntimeError('Desktop OpenGL 4.1 functions unavailable')
            for name, token in [('vendor', 0x1F00), ('renderer', 0x1F01),
                                ('version', 0x1F02), ('glsl', 0x8B8C)]:
                raw = self.funcs.glGetString(token)
                self.gl_info[name] = raw if isinstance(raw, str) else bytes(raw).decode('utf-8', 'replace')
            self.vao = QOpenGLVertexArrayObject()
            self.blitter = QOpenGLTextureBlitter()
            if not self.vao.create() or not self.blitter.create():
                raise RuntimeError('OpenGL draw resources unavailable')
            self.ready = True
            self.compile_program()
        except Exception as exc:
            self.fail(exc)

    def sync_timer(self):
        active = (self.fps and self.isVisible() and not self.window().isMinimized()
                  and not self.error and not self.cleaned)
        if active:
            self.timer.start(round(1000 / self.fps))
        else:
            self.timer.stop()

    def set_rate(self, fps):
        if fps not in (0, 15, 20, 30):
            raise ValueError('Supported animation rates: 0, 15, 20, 30')
        self.fps = fps
        self.sync_timer()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_timer()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintGL(self):
        if not self.ready or self.error or self.cleaned:
            return
        started = time.perf_counter()
        try:
            if self.needs_compile:
                self.compile_program()
            w = max(1, round(self.width() * self.devicePixelRatioF() * self.scale))
            h = max(1, round(self.height() * self.devicePixelRatioF() * self.scale))
            if self.fbo is None or self.fbo.width() != w or self.fbo.height() != h:
                self.fbo = QOpenGLFramebufferObject(w, h)
                if not self.fbo.isValid():
                    raise RuntimeError('Render framebuffer unavailable')
            self.fbo.bind()
            self.funcs.glViewport(0, 0, w, h)
            self.program.bind()
            self.program.setUniformValue('u_resolution', QVector2D(w, h))
            self.program.setUniformValue('u_time', float(started-self.clock) if self.fps else 0.)
            self.program.setUniformValue('u_mouse', QVector2D(0, 0))
            self.program.setUniformValue('u_pixelRatio', float(self.devicePixelRatioF()))
            if self.program.uniformLocation('iResolution') >= 0:
                self.program.setUniformValue('iResolution', QVector3D(w, h, 1))
            if self.program.uniformLocation('iTime') >= 0:
                self.program.setUniformValue('iTime', float(started-self.clock) if self.fps else 0.)
            if self.shader == SHADER:
                for index, color in enumerate(PALETTE):
                    self.program.setUniformValue(f'u_palette[{index}]', QVector3D(*color))
                for name, value in DEFAULTS.items():
                    self.program.setUniformValue(name, value)
            self.vao.bind()
            self.funcs.glDrawArrays(0x0004, 0, 3)
            self.vao.release()
            self.program.release()
            self.funcs.glBindFramebuffer(0x8D40, self.defaultFramebufferObject())
            self.funcs.glViewport(0, 0, round(self.width()*self.devicePixelRatioF()),
                                  round(self.height()*self.devicePixelRatioF()))
            self.blitter.bind()
            self.blitter.blit(self.fbo.texture(), QMatrix4x4(), QOpenGLTextureBlitter.Origin.OriginBottomLeft)
            self.blitter.release()
            self.frames += 1
            self.cpu_draw_ms = (self.cpu_draw_ms + [(time.perf_counter()-started)*1000])[-300:]
            self.frame_times = (self.frame_times + [started])[-300:]
            code = self.funcs.glGetError()
            if code:
                raise RuntimeError(f'OpenGL error {code}')
        except Exception as exc:
            self.fail(exc)

    def cleanup(self):
        if self.cleaned:
            return
        self.timer.stop()
        try:
            self.makeCurrent()
            self.fbo = None
            if self.blitter:
                self.blitter.destroy()
            if self.vao:
                self.vao.destroy()
            if self.program:
                self.program.removeAllShaders()
            self.blitter = self.vao = self.program = None
            self.doneCurrent()
        except Exception as exc:
            self.cleanup_errors.append(str(exc))
        self.cleaned = True


class HeroSurface(QWidget):
    """Exactly one renderer, created lazily only when animation is requested."""
    def __init__(self, content, parent=None, force_fallback=False, shader=NO_SELECTION_SHADER):
        super().__init__(parent)
        self.layers = QStackedLayout(self)
        self.layers.setContentsMargins(0, 0, 0, 0)
        self.layers.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.static = StaticPanel()
        self.layers.addWidget(self.static)
        self.scrim = MetadataScrim()
        self.layers.addWidget(self.scrim)
        self.content = content
        self.layers.addWidget(content)
        self.layers.setCurrentWidget(content)
        self.gl = None
        self.shader = shader
        self.static.set_shader(shader)
        self.unavailable_reason = GL_IMPORT_ERROR or ('OpenGL disabled for this review' if force_fallback else '')
        self.fallback_reason = self.unavailable_reason
        self.provider_id = None
        self.fps = 0
        self.guard = QTimer(self)
        self.guard.setSingleShot(True)
        self.guard.timeout.connect(self.check_context)

    def set_animation(self, fps):
        if fps not in (0, 15, 20, 30):
            raise ValueError('Supported animation rates: 0, 15, 20, 30')
        self.fps = fps
        if not fps:
            if self.gl:
                self.gl.set_rate(0)
                self.gl.hide()
            self.static.show()
            return
        if self.fallback_reason:
            return
        if self.gl is None:
            if not context_available():
                self.fallback('Desktop OpenGL 4.1 context unavailable')
                self.unavailable_reason = self.fallback_reason
                return
            self.gl = ShaderPanel(self.fallback, self.shader)
            self.layers.insertWidget(1, self.gl)
            self.layers.setCurrentWidget(self.content)
            self.guard.start(3000)
        self.gl.show()
        self.static.hide()
        self.gl.set_rate(fps)

    def set_provider(self, provider_id):
        self.provider_id = provider_id if provider_id in PROVIDER_PRESETS else None
        # Unified hero experiment: retain provider identity and original assets.
        shader = NO_SELECTION_SHADER
        self.set_shader(shader)

    def set_shader(self, shader):
        shader = Path(shader)
        if shader == self.shader:
            return
        self.shader = shader
        self.static.set_shader(shader)
        self.fallback_reason = self.unavailable_reason
        self.setToolTip('Static hero: '+self.fallback_reason if self.fallback_reason else '')
        if self.gl:
            self.gl.set_shader(shader)
        self.set_animation(self.fps)

    def check_context(self):
        if self.gl and not self.gl.ready:
            self.fallback('OpenGL initialization unavailable')

    def fallback(self, reason):
        self.fallback_reason = str(reason)
        if self.gl:
            self.gl.timer.stop()
            self.gl.hide()
        self.static.show()
        self.setToolTip('Static hero: ' + self.fallback_reason)

    def cleanup(self):
        self.guard.stop()
        if self.gl:
            self.gl.cleanup()
