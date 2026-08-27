from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog


class MangaNanaAction(InterfaceAction):
    name = 'MangaNana'
    action_spec = (
        'MangaNana',
        'images/icon.png',
        'Download manga from MangaDex and add it to calibre',
        None,
    )
    action_add_menu = False

    def genesis(self):
        # Load the icon through calibre's plugin resource loader. get_icons is
        # injected into plugin modules by calibre's ZIP plugin loader.
        try:
            icon = get_icons('images/icon.png', 'MangaNana')
            if icon is not None and not icon.isNull():
                self.qaction.setIcon(icon)
        except Exception:
            pass

        # Keep plugin startup deliberately lightweight. The full MangaNana UI
        # is imported only after the toolbar action is clicked, so a problem in
        # the downloader/dialog code cannot prevent the action from appearing
        # in calibre's toolbar customization list.
        self.qaction.triggered.connect(self.show_dialog)

    def initialization_complete(self):
        pass

    def library_changed(self, db):
        pass

    def location_selected(self, loc):
        pass

    def shutting_down(self):
        pass

    def show_dialog(self):
        try:
            from calibre_plugins.manganana.main import MangaNanaDialog
            d = MangaNanaDialog(self.gui, self.qaction.icon())
            d.exec()
        except Exception as e:
            import traceback
            error_dialog(
                self.gui,
                'MangaNana error',
                str(e),
                det_msg=traceback.format_exc(),
                show=True,
            )
