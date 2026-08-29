from calibre.customize import InterfaceActionBase
from calibre_plugins.manganana.version_info import CALIBRE_VERSION


class MangaNanaCalibrePlugin(InterfaceActionBase):
    name = 'MangaNana'
    description = 'Download manga from MangaDex and add it directly to the current calibre library.'
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'MangaNana Project'
    version = CALIBRE_VERSION
    minimum_calibre_version = (7, 0, 0)
    actual_plugin = 'calibre_plugins.manganana.ui:MangaNanaAction'
