"""Pure ProcessingSettings presets; device/screen emulation is separate."""
from dataclasses import dataclass

try:
    from .image_processing import ProcessingSettings
except ImportError:
    from image_processing import ProcessingSettings


PRESET_SCHEMA_VERSION = 1
CUSTOM_PRESET_ID = 'custom'


@dataclass(frozen=True)
class ProcessingPreset:
    preset_id: str
    name: str
    settings: ProcessingSettings
    builtin: bool = True


BUILTIN_PRESETS = (
    ProcessingPreset('original','Original',ProcessingSettings()),
    ProcessingPreset('bw_manga','B&W Manga',ProcessingSettings(
        brightness=1,contrast=1.15,gamma=1,saturation=1,sharpness=1.10,grayscale=True)),
    ProcessingPreset('high_contrast_manga','High Contrast B&W',ProcessingSettings(
        brightness=1,contrast=1.30,gamma=.95,saturation=1,sharpness=1.20,grayscale=True)),
    ProcessingPreset('soft_grayscale','Soft Grayscale',ProcessingSettings(
        brightness=1,contrast=.95,gamma=1.05,saturation=1,sharpness=1,grayscale=True)),
    ProcessingPreset('color_enhancement','Color Enhancement',ProcessingSettings(
        brightness=1,contrast=1.08,gamma=1,saturation=1.25,sharpness=1.10,grayscale=False)),
)
BUILTIN_PRESETS_BY_ID={preset.preset_id:preset for preset in BUILTIN_PRESETS}
BUILTIN_PRESETS_BY_NAME={preset.name.casefold():preset for preset in BUILTIN_PRESETS}


def normalized_settings_snapshot(settings):
    """Return the canonical immutable settings object shared by all consumers."""
    if not isinstance(settings,ProcessingSettings):
        raise TypeError('Expected ProcessingSettings.')
    return settings


def settings_to_payload(settings):
    settings=normalized_settings_snapshot(settings)
    return {
        'version':PRESET_SCHEMA_VERSION,
        'brightness':float(settings.brightness),'contrast':float(settings.contrast),
        'gamma':float(settings.gamma),'saturation':float(settings.saturation),
        'sharpness':float(settings.sharpness),'grayscale':bool(settings.grayscale),
        'output_depth':int(settings.output_depth),'dithering':str(settings.dithering),
        'dither_strength':float(settings.dither_strength),
    }


def settings_from_payload(payload):
    """Strictly decode one complete schema-v1 payload through ProcessingSettings."""
    if not isinstance(payload,dict) or payload.get('version') != PRESET_SCHEMA_VERSION:
        raise ValueError('Unsupported or malformed processing preset schema.')
    required=set(settings_to_payload(ProcessingSettings()))
    if set(payload) != required:
        raise ValueError('Processing preset fields are incomplete or unknown.')
    grayscale=payload['grayscale']
    if not isinstance(grayscale,bool):
        raise ValueError('Processing preset grayscale must be boolean.')
    return ProcessingSettings(
        brightness=float(payload['brightness']),contrast=float(payload['contrast']),
        gamma=float(payload['gamma']),saturation=float(payload['saturation']),
        sharpness=float(payload['sharpness']),grayscale=grayscale,
        output_depth=int(payload['output_depth']),dithering=str(payload['dithering']),
        dither_strength=float(payload['dither_strength']),
    )


def validate_user_preset_name(name, existing_names=(), current_name=None):
    cleaned=' '.join(str(name or '').split())
    folded=cleaned.casefold()
    if not cleaned:
        raise ValueError('Preset name cannot be empty.')
    if folded == 'custom':
        raise ValueError('“Custom” is reserved for unsaved processing state.')
    if folded in BUILTIN_PRESETS_BY_NAME:
        raise ValueError('Built-in preset names cannot be overwritten.')
    current=str(current_name or '').casefold()
    if any(str(value).casefold()==folded and str(value).casefold()!=current for value in existing_names):
        raise ValueError('A user preset with that name already exists.')
    return cleaned


def load_user_presets(payload):
    """Skip malformed entries independently; never prevent dialog construction."""
    result=[]
    if not isinstance(payload,dict):
        return ()
    for raw_name,raw_settings in payload.items():
        try:
            name=validate_user_preset_name(raw_name,(preset.name for preset in result))
            settings=settings_from_payload(raw_settings)
        except (TypeError,ValueError,OverflowError):
            continue
        result.append(ProcessingPreset('user:'+name,name,settings,False))
    return tuple(result)


def user_presets_payload(presets):
    return {preset.name:settings_to_payload(preset.settings)
            for preset in presets if not preset.builtin}


def matching_preset(settings,user_presets=()):
    settings=normalized_settings_snapshot(settings)
    for preset in (*BUILTIN_PRESETS,*tuple(user_presets)):
        if preset.settings == settings:
            return preset
    return None


def save_user_preset(presets,name,settings,current_name=None):
    """Add/update/rename one user preset and return immutable ordered definitions."""
    presets=tuple(presets)
    name=validate_user_preset_name(name,(p.name for p in presets),current_name)
    settings=normalized_settings_snapshot(settings)
    current_folded=str(current_name or '').casefold()
    replacement=ProcessingPreset('user:'+name,name,settings,False)
    if current_name is None:
        return (*presets,replacement)
    if not current_folded or not any(not p.builtin and p.name.casefold()==current_folded for p in presets):
        raise ValueError('Only user presets can be updated or renamed.')
    return tuple(replacement if p.name.casefold()==current_folded else p for p in presets)


def delete_user_preset(presets,name):
    presets=tuple(presets); folded=str(name or '').casefold()
    if folded in BUILTIN_PRESETS_BY_NAME or not any(not p.builtin and p.name.casefold()==folded for p in presets):
        raise ValueError('Only user presets can be deleted.')
    return tuple(p for p in presets if p.name.casefold()!=folded)
