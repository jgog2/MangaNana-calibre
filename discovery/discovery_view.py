"""Virtualized grouped/flat discovery, independent of acquisition authority."""
from collections import OrderedDict
from qt.core import (Qt,QAbstractItemModel,QModelIndex,QTreeView,QStyledItemDelegate,
    QStyle,QSize,QColor,QPen,QRect,QPoint,QFontMetrics,QTimer,QAbstractItemView,QPainterPath,QObject)
from calibre_plugins.manganana.discovery.discovery_groups import group_records, provider_key
from calibre_plugins.manganana.presentation.choose_manga_design import listing_chapter_count
from calibre_plugins.manganana.discovery.canonical_identity import edition_display_label
from calibre_plugins.manganana.providers.provider_branding import provider_brand
from calibre_plugins.manganana.presentation.mangaanka_presentation import UI_ACCENT


class Node:
    def __init__(self,record=None,group=None,parent=None,row=0):
        self.record=record;self.group=group;self.parent=parent;self.row=row;self.children=[]


class DiscoveryModel(QAbstractItemModel):
    def __init__(self,parent=None):
        super().__init__(parent);self.roots=[];self.by_provider={}

    def replace(self,records,grouped):
        self.beginResetModel();self.roots=[];self.by_provider={}
        for i,group in enumerate(group_records(records) if grouped else records):
            root=Node(group=group,row=i) if grouped else Node(record=group,row=i)
            self.roots.append(root)
            if grouped:
                for j,record in enumerate(group.records):root.children.append(Node(record=record,parent=root,row=j))
            for leaf in root.children if grouped else [root]:self.by_provider[provider_key(leaf.record)]=leaf
        self.endResetModel()

    def rowCount(self,parent=QModelIndex()):
        if parent.isValid() and parent.column()!=0:return 0
        return len(parent.internalPointer().children) if parent.isValid() else len(self.roots)

    def columnCount(self,parent=QModelIndex()):return 1

    def index(self,row,column,parent=QModelIndex()):
        if column!=0 or row<0:return QModelIndex()
        rows=parent.internalPointer().children if parent.isValid() else self.roots
        return self.createIndex(row,column,rows[row]) if row<len(rows) else QModelIndex()

    def parent(self,index):
        node=index.internalPointer() if index.isValid() else None
        return self.createIndex(node.parent.row,0,node.parent) if node and node.parent else QModelIndex()

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():return None
        node=index.internalPointer();row=node.record or node.group.records[0]
        if role==Qt.ItemDataRole.UserRole:return node.record
        if role==Qt.ItemDataRole.DisplayRole:return row.get('title') or 'Untitled'
        if role in (Qt.ItemDataRole.ToolTipRole,Qt.ItemDataRole.AccessibleTextRole,Qt.ItemDataRole.AccessibleDescriptionRole):
            if node.group:return node.group.title+' — '+str(len(node.children))+' provider listings; expand to choose an exact source'
            count=listing_chapter_count(row)
            favorites=getattr(getattr(QObject.parent(self),'dialog',None),'saved_manga',None)
            saved=('Saved Manga; H removes this listing' if favorites.store.contains(row) else 'H saves this provider listing') if favorites else ''
            return ' — '.join(filter(None,[row.get('title'),row.get('source_name') or row.get('source_id'),row.get('badge') or edition_display_label(row),f'{count} chapters' if count is not None else '',saved]))
        return None

    def flags(self,index):
        return Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable if index.isValid() else Qt.ItemFlag.NoItemFlags

    def provider_index(self,key):
        node=self.by_provider.get(key)
        return self.createIndex(node.row,0,node) if node else QModelIndex()

    def artwork_changed(self,url):
        """Resolve current nodes by URL after resets; retain no stale indices."""
        if not url:return
        for root in self.roots:
            representative=root.record or root.group.records[0]
            if representative.get('cover_url')==url:
                index=self.createIndex(root.row,0,root);self.dataChanged.emit(index,index,[])
            for leaf in root.children:
                if leaf.record.get('cover_url')==url:
                    index=self.createIndex(leaf.row,0,leaf);self.dataChanged.emit(index,index,[])


class DiscoveryDelegate(QStyledItemDelegate):
    def __init__(self,view):super().__init__(view);self.view=view;self.badges={};self.geometry=[]

    def sizeHint(self,option,index):return QSize(0,60)

    @staticmethod
    def heart_rect(rect):
        return QRect(rect.right()-30,rect.y()+14,28,28)

    def paint(self,painter,option,index):
        node=index.internalPointer();row=node.record or node.group.records[0];rect=option.rect
        audit=getattr(self.view.dialog,'thumbnail_audit',None)
        if audit is not None:
            audit.event('paint',provider=row.get('source_id'),id=row.get('id'),url=row.get('cover_url'),grouped=bool(node.group),rect=[rect.x(),rect.y(),rect.width(),rect.height()],cached=row.get('cover_url') in getattr(self.view.dialog,'_search_image_cache',self.view.dialog._image_cache))
        painter.save();painter.setClipRect(rect);painter.setRenderHint(painter.RenderHint.Antialiasing)
        selected=bool(option.state & QStyle.StateFlag.State_Selected)
        current=self.view.dialog.search_results.currentItem()
        if node.group and not self.view.isExpanded(index) and current:
            selected=any(provider_key(r)==provider_key(current.data(256) or {}) for r in node.group.records)
        painter.fillRect(rect,QColor('#29453f' if selected else '#1c282b' if option.state & QStyle.StateFlag.State_MouseOver else '#101922'))
        painter.setPen(QColor('#2b383e'));painter.drawLine(rect.bottomLeft(),rect.bottomRight())
        x=rect.x()+8;cover=QRect(x,rect.y()+5,36,50)
        url=row.get('cover_url') or '';pix=self.view.pixmap(url)
        if pix is not None and not pix.isNull():
            target=QRect(cover);target.setSize(pix.deviceIndependentSize().toSize());target.moveCenter(cover.center());painter.drawPixmap(target,pix)
        else:
            painter.fillRect(cover,QColor('#263a40'));painter.setPen(QColor('#52676d'));painter.drawRoundedRect(cover,3,3)
        x=cover.right()+9;right=rect.right()-8
        favorites=getattr(self.view.dialog,'saved_manga',None)
        if node.record and favorites and self.view.saved_mode:
            from calibre_plugins.manganana.discovery.saved_manga_ui import HEART_COLOR
            heart=self.heart_rect(rect)
            painter.setPen(QPen(QColor(HEART_COLOR),1.6))
            painter.setBrush(QColor(HEART_COLOR) if favorites.store.contains(row) else Qt.BrushStyle.NoBrush)
            path=QPainterPath();left=heart.x()+5;top=heart.y()+5
            path.moveTo(left+9,top+17)
            path.cubicTo(left-9,top+5,left+3,top-5,left+9,top+3)
            path.cubicTo(left+15,top-5,left+27,top+5,left+9,top+17)
            painter.drawPath(path)
            right=heart.left()-4
        font=option.font;font.setPixelSize(13);font.setBold(bool(node.group));painter.setFont(font);metrics=QFontMetrics(font)
        chip=None
        if node.group:
            label=str(len(node.children))+' source'+('s' if len(node.children)!=1 else '')
            width=metrics.horizontalAdvance(label)+14
        else:
            brand=provider_brand(row.get('source_id'));label=row.get('source_name') or brand.display_name
            chip=brand;width=metrics.horizontalAdvance(label)+28
        badge=QRect(right-width,rect.y()+16,width,22)
        title_rect=QRect(x,rect.y()+16,max(0,badge.left()-x-5),22)
        painter.setPen(QColor('#edf1f0'));painter.drawText(title_rect,Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(str(row.get('title') or 'Untitled'),Qt.TextElideMode.ElideRight,title_rect.width()))
        painter.setPen(QColor(chip.accent_color if chip else '#405952'));painter.setBrush(QColor('#1b282d'))
        painter.drawRoundedRect(badge,9,9);painter.setPen(QColor('#e7eeeb'))
        if chip:
            if chip.source_id not in self.badges:
                from calibre_plugins.manganana.app.main import _provider_icon_pixmap
                self.badges[chip.source_id]=_provider_icon_pixmap(chip.icon_path)
            icon=self.badges[chip.source_id]
            if icon is not None:painter.drawPixmap(QRect(badge.x()+5,badge.y()+4,14,14),icon)
        painter.drawText(badge.adjusted(22 if chip else 7,0,-5,0),Qt.AlignmentFlag.AlignVCenter,label)
        count=listing_chapter_count(row) if not node.group else None
        edition=row.get('badge') or edition_display_label(row)
        font.setPixelSize(10);font.setBold(False);painter.setFont(font);sub=QFontMetrics(font)
        detail_rect=QRect(x,rect.y()+38,max(0,right-x),16)
        if edition:
            pill=QRect(x,detail_rect.y(),min(detail_rect.width(),sub.horizontalAdvance(edition)+12),16)
            painter.setPen(QColor('#e5e9eb' if edition=='COLOR' else '#657978'));painter.setBrush(QColor('#263238'))
            painter.drawRoundedRect(pill,5,5);painter.setPen(QColor('#ffffff' if edition=='COLOR' else '#d5dfdc'))
            painter.drawText(pill.adjusted(6,0,-6,0),Qt.AlignmentFlag.AlignVCenter,sub.elidedText(edition,Qt.TextElideMode.ElideRight,max(0,pill.width()-12)))
            detail_rect.setLeft(pill.right()+7)
        if count is not None:
            painter.setPen(QColor('#aebdbb'))
            painter.drawText(detail_rect,Qt.AlignmentFlag.AlignVCenter,sub.elidedText(f'{count} chapters',Qt.TextElideMode.ElideRight,max(0,detail_rect.width())))
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor(UI_ACCENT),1));painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRoundedRect(rect.adjusted(1,1,-2,-2),5,5)
        painter.restore()


class DiscoveryView(QTreeView):
    def __init__(self,dialog):
        super().__init__();self.dialog=dialog;self.grouped=True;self.saved_mode=False;self.records=[];self.expansion=OrderedDict();self.query=''
        self._resetting=False;self.setObjectName('groupedDiscovery');self.setAccessibleName('Manga discovery results')
        self.setModel(DiscoveryModel(self));self.setItemDelegate(DiscoveryDelegate(self))
        self.setHeaderHidden(True);self.setIndentation(16);self.setUniformRowHeights(True);self.setAnimated(False)
        self.setExpandsOnDoubleClick(False);self.setAllColumnsShowFocus(True);self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(16);self.setMinimumHeight(80)
        self.setStyleSheet('QTreeView {background:transparent;border:0;outline:0;} QTreeView::branch {background:transparent;}')
        self.clicked.connect(self.activate_index);self.activated.connect(self.activate_index)
        self.expanded.connect(lambda idx:self.remember(idx,True));self.collapsed.connect(lambda idx:self.remember(idx,False))
        self.verticalScrollBar().valueChanged.connect(lambda *_:self.schedule_thumbs())
        self.thumb_timer=QTimer(self);self.thumb_timer.setSingleShot(True);self.thumb_timer.setInterval(0)
        self.thumb_timer.timeout.connect(dialog._load_visible_search_thumbs)

    def drawBranches(self,painter,rect,index):
        if not index.internalPointer().group:return
        painter.save();painter.setPen(QPen(QColor('#bacbc5'),1.5))
        center=rect.center()
        if self.isExpanded(index):
            points=[center+QPoint(-4,-2),center+QPoint(0,2),center+QPoint(4,-2)]
        else:points=[center+QPoint(-2,-4),center+QPoint(2,0),center+QPoint(-2,4)]
        painter.drawLine(points[0],points[1]);painter.drawLine(points[1],points[2]);painter.restore()

    def remember(self,index,expanded):
        if not self._resetting and index.isValid() and index.internalPointer().group:
            key=(self.query,index.internalPointer().group.key)
            if expanded:self.expansion[key]=True;self.expansion.move_to_end(key)
            else:self.expansion.pop(key,None)
            while len(self.expansion)>512:self.expansion.popitem(last=False)
            self.schedule_thumbs()

    def set_records(self,records):
        scroll=self.verticalScrollBar().value();selected=self.dialog.search_results.currentItem()
        key=provider_key(selected.data(256) or {}) if selected else None
        self.records=[dict(r) for r in records];self.query=self.dialog._search_query
        self._resetting=True;self.model().replace(self.records,self.grouped and not self.saved_mode)
        for i,node in enumerate(self.model().roots):
            if node.group and (self.query,node.group.key) in self.expansion:self.expand(self.model().index(i,0))
        self._resetting=False
        self.sync_selection(key,reveal=False);self.verticalScrollBar().setValue(scroll);self.schedule_thumbs()

    def set_grouped(self,grouped):
        if self.grouped==bool(grouped):return
        self.grouped=bool(grouped);self.setRootIsDecorated(self.grouped);self.set_records(self.records)

    def sync_selection(self,key=None,reveal=True):
        if key is None:
            current=self.dialog.search_results.currentItem();key=provider_key(current.data(256) or {}) if current else None
        index=self.model().provider_index(key)
        if index.isValid():
            if reveal and index.parent().isValid():self.expand(index.parent())
            self.setCurrentIndex(index)
            if reveal:self.scrollTo(index)
        else:self.clearSelection();self.setCurrentIndex(QModelIndex())

    def activate_index(self,index):
        if not index.isValid():return
        node=index.internalPointer()
        if node.group:self.setExpanded(index,not self.isExpanded(index));return
        if self.saved_mode:
            self.dialog.saved_manga.open(node.record);return
        item=self.dialog._discovery_items.get(provider_key(node.record))
        if item is not None:self.dialog.use_search_result(item)

    def mousePressEvent(self,event):
        index=self.indexAt(event.position().toPoint())
        if (self.saved_mode and event.button()==Qt.MouseButton.LeftButton and index.isValid() and index.internalPointer().record
                and self.itemDelegate().heart_rect(self.visualRect(index)).contains(event.position().toPoint())
                and hasattr(self.dialog,'saved_manga')):
            self.dialog.saved_manga.toggle(index.internalPointer().record)
            self._heart_press=True;event.accept();return
        self._heart_press=False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self,event):
        if getattr(self,'_heart_press',False):
            self._heart_press=False;event.accept();return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        index=self.indexAt(event.position().toPoint())
        if (self.saved_mode and index.isValid() and index.internalPointer().record and
                self.itemDelegate().heart_rect(self.visualRect(index)).contains(event.position().toPoint())):
            self.mousePressEvent(event);return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self,event):
        index=self.currentIndex()
        if (event.key()==Qt.Key.Key_H and index.isValid() and index.internalPointer().record
                and hasattr(self.dialog,'saved_manga')):
            self.dialog.saved_manga.toggle(index.internalPointer().record);event.accept();return
        super().keyPressEvent(event)

    def mouseMoveEvent(self,event):
        index=self.indexAt(event.position().toPoint())
        heart=(self.saved_mode and index.isValid() and index.internalPointer().record and
            self.itemDelegate().heart_rect(self.visualRect(index)).contains(event.position().toPoint()))
        self.setToolTip(('Remove from Saved Manga' if self.dialog.saved_manga.store.contains(index.internalPointer().record)
            else 'Save this provider listing') if heart and hasattr(self.dialog,'saved_manga') else '')
        super().mouseMoveEvent(event)

    def schedule_thumbs(self):self.thumb_timer.start()

    def visible_records(self):
        records=[];index=self.indexAt(self.viewport().rect().topLeft()+QPoint(24,1))
        if not index.isValid():index=self.model().index(0,0)
        budget=max(4,self.viewport().height()//60+3)
        while index.isValid() and len(records)<budget:
            node=index.internalPointer();records.append(node.record or node.group.records[0]);index=self.indexBelow(index)
        return records

    def pixmap(self,url):
        if hasattr(self.dialog,'_search_pixmap'):return self.dialog._search_pixmap(url)
        if not url or url not in self.dialog._image_cache:return None
        return self.dialog._pix_for_url(url,36,50)
