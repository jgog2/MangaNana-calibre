from calibre.customize import InterfaceActionBase
from calibre_plugins.manganana.version_info import CALIBRE_VERSION


class MangaNanaCalibrePlugin(InterfaceActionBase):
    name = 'MangaNana'
    description = "Reading manga shouldn't turn into a damn IT project."
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'jgog'
    version = CALIBRE_VERSION
    minimum_calibre_version = (7, 0, 0)
    actual_plugin = 'calibre_plugins.manganana.ui:MangaNanaAction'
