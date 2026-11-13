"""Shared store colours and installation markers for table and cover views."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QIcon,QPainter,QPen,QPixmap

STORE_COLORS={'Steam':'#468bd3','GOG':'#b36be3','Epic':'#8896a8',
              'Amazon':'#efa33c','EA':'#ef6c7b','Rockstar':'#d5bf39'}

def store_background(store,palette):
    base=palette.base().color();accent=QColor(STORE_COLORS.get(store,'#8896a8'))
    amount=.23 if base.lightness()<128 else .16
    return QColor(*(round(a*(1-amount)+b*amount) for a,b in zip(base.getRgb()[:3],accent.getRgb()[:3])))

def is_installed(row):return row.get('installation_status')=='Installed'

def installed_icon():
    pix=QPixmap(20,20);pix.fill(Qt.transparent);p=QPainter(pix);p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen);p.setBrush(QColor('#24764a'));p.drawEllipse(1,1,18,18)
    p.setPen(QPen(QColor('white'),2.2,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
    p.drawLine(5,10,9,14);p.drawLine(9,14,15,7);p.end();return QIcon(pix)
