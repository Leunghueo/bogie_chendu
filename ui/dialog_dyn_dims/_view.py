# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file '_view.ui'
##
## Created by: Qt User Interface Compiler version 6.8.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(1239, 836)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(Form.sizePolicy().hasHeightForWidth())
        Form.setSizePolicy(sizePolicy)
        self.verticalLayout = QVBoxLayout(Form)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(-1, 9, -1, -1)
        self.widget = QWidget(Form)
        self.widget.setObjectName(u"widget")
        self.horizontalLayout = QHBoxLayout(self.widget)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.widget_2 = QWidget(self.widget)
        self.widget_2.setObjectName(u"widget_2")
        self.widget_2.setMinimumSize(QSize(1100, 800))
        self.widget_2.setStyleSheet(u"QLabel{\n"
"    padding: 1px;\n"
"    background: rgb(0, 0, 255);\n"
"    border: 1px solid #16364b;\n"
"	color: rgb(255, 255, 255);\n"
"	font: 9pt \"Microsoft YaHei UI\";\n"
"}\n"
"\n"
"QPushButton {\n"
"    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f8fbe, stop:1 #41b7dc);\n"
"    color: #ffffff;\n"
"    font-weight: 600;\n"
"    border: 1px solid #7bcbe7;\n"
"    border-radius: 3px;\n"
"    padding: 2px;\n"
"}")
        self.lb_bg = QLabel(self.widget_2)
        self.lb_bg.setObjectName(u"lb_bg")
        self.lb_bg.setGeometry(QRect(107, 57, 1001, 591))
        self.lb_bg.setMinimumSize(QSize(0, 0))
        self.lb_bg.setStyleSheet(u"border-color: rgb(255, 255, 255);")
        self.lb_bg.setPixmap(QPixmap(u"../../runtime/res/image/dim.png"))
        self.lb_bg.setScaledContents(True)
        self.bench4_ncj = QLabel(self.widget_2)
        self.bench4_ncj.setObjectName(u"bench4_ncj")
        self.bench4_ncj.setGeometry(QRect(272, 169, 71, 16))
        self.bench4_ncj.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.bench4_zj = QLabel(self.widget_2)
        self.bench4_zj.setObjectName(u"bench4_zj")
        self.bench4_zj.setGeometry(QRect(412, 170, 71, 16))
        self.bench4_zj.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.l24_cal = QLabel(self.widget_2)
        self.l24_cal.setObjectName(u"l24_cal")
        self.l24_cal.setGeometry(QRect(561, 170, 71, 16))
        self.l24_cal.setStyleSheet(u"background-color:  rgb(186, 0, 0);")
        self.bench2_ncj = QLabel(self.widget_2)
        self.bench2_ncj.setObjectName(u"bench2_ncj")
        self.bench2_ncj.setGeometry(QRect(850, 171, 71, 16))
        self.bench2_ncj.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.bench2_zj = QLabel(self.widget_2)
        self.bench2_zj.setObjectName(u"bench2_zj")
        self.bench2_zj.setGeometry(QRect(704, 171, 71, 16))
        self.bench2_zj.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.w34_cal = QLabel(self.widget_2)
        self.w34_cal.setObjectName(u"w34_cal")
        self.w34_cal.setGeometry(QRect(432, 346, 71, 16))
        self.w34_cal.setStyleSheet(u"background-color: rgb(186, 0, 0);")
        self.w12_cal = QLabel(self.widget_2)
        self.w12_cal.setObjectName(u"w12_cal")
        self.w12_cal.setGeometry(QRect(682, 346, 71, 16))
        self.w12_cal.setStyleSheet(u"background-color: rgb(186, 0, 0);")
        self.bench3_zj = QLabel(self.widget_2)
        self.bench3_zj.setObjectName(u"bench3_zj")
        self.bench3_zj.setGeometry(QRect(409, 535, 71, 16))
        self.bench3_zj.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.bench3_ncj = QLabel(self.widget_2)
        self.bench3_ncj.setObjectName(u"bench3_ncj")
        self.bench3_ncj.setGeometry(QRect(272, 536, 71, 16))
        self.bench3_ncj.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.bench1_ncj = QLabel(self.widget_2)
        self.bench1_ncj.setObjectName(u"bench1_ncj")
        self.bench1_ncj.setGeometry(QRect(845, 534, 71, 16))
        self.bench1_ncj.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.bench1_zj = QLabel(self.widget_2)
        self.bench1_zj.setObjectName(u"bench1_zj")
        self.bench1_zj.setGeometry(QRect(699, 535, 71, 16))
        self.bench1_zj.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.l13_cal = QLabel(self.widget_2)
        self.l13_cal.setObjectName(u"l13_cal")
        self.l13_cal.setGeometry(QRect(562, 520, 71, 16))
        self.l13_cal.setStyleSheet(u"background-color: rgb(186, 0, 0);")
        self.label_36_cal = QLabel(self.widget_2)
        self.label_36_cal.setObjectName(u"label_36_cal")
        self.label_36_cal.setGeometry(QRect(571, 150, 51, 20))
        self.label_36_cal.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_40_cal = QLabel(self.widget_2)
        self.label_40_cal.setObjectName(u"label_40_cal")
        self.label_40_cal.setGeometry(QRect(442, 326, 61, 16))
        self.label_40_cal.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_41_cal = QLabel(self.widget_2)
        self.label_41_cal.setObjectName(u"label_41_cal")
        self.label_41_cal.setGeometry(QRect(692, 326, 61, 16))
        self.label_41_cal.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_46_cal = QLabel(self.widget_2)
        self.label_46_cal.setObjectName(u"label_46_cal")
        self.label_46_cal.setGeometry(QRect(570, 501, 51, 20))
        self.label_46_cal.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_44 = QLabel(self.widget_2)
        self.label_44.setObjectName(u"label_44")
        self.label_44.setGeometry(QRect(404, 153, 88, 16))
        self.label_44.setMinimumSize(QSize(88, 16))
        self.label_44.setMaximumSize(QSize(88, 16777215))
        font = QFont()
        font.setFamilies([u"Microsoft YaHei UI"])
        font.setPointSize(9)
        font.setBold(False)
        font.setItalic(False)
        self.label_44.setFont(font)
        self.label_44.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.bench4_w = QLabel(self.widget_2)
        self.bench4_w.setObjectName(u"bench4_w")
        self.bench4_w.setGeometry(QRect(272, 236, 71, 16))
        self.bench4_w.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.label_47 = QLabel(self.widget_2)
        self.label_47.setObjectName(u"label_47")
        self.label_47.setGeometry(QRect(207, 236, 61, 16))
        self.label_47.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_48 = QLabel(self.widget_2)
        self.label_48.setObjectName(u"label_48")
        self.label_48.setGeometry(QRect(922, 236, 81, 16))
        self.label_48.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.bench2_w = QLabel(self.widget_2)
        self.bench2_w.setObjectName(u"bench2_w")
        self.bench2_w.setGeometry(QRect(847, 238, 71, 16))
        self.bench2_w.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.label_51 = QLabel(self.widget_2)
        self.label_51.setObjectName(u"label_51")
        self.label_51.setGeometry(QRect(207, 455, 61, 16))
        self.label_51.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.bench3_w = QLabel(self.widget_2)
        self.bench3_w.setObjectName(u"bench3_w")
        self.bench3_w.setGeometry(QRect(272, 455, 71, 16))
        self.bench3_w.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.label_52 = QLabel(self.widget_2)
        self.label_52.setObjectName(u"label_52")
        self.label_52.setGeometry(QRect(928, 453, 61, 16))
        self.label_52.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.bench1_w = QLabel(self.widget_2)
        self.bench1_w.setObjectName(u"bench1_w")
        self.bench1_w.setGeometry(QRect(848, 455, 71, 16))
        self.bench1_w.setStyleSheet(u"background-color: rgb(255, 85, 0);")
        self.label_58 = QLabel(self.widget_2)
        self.label_58.setObjectName(u"label_58")
        self.label_58.setGeometry(QRect(857, 154, 81, 18))
        self.label_58.setFont(font)
        self.label_58.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_59 = QLabel(self.widget_2)
        self.label_59.setObjectName(u"label_59")
        self.label_59.setGeometry(QRect(857, 516, 81, 18))
        self.label_59.setFont(font)
        self.label_59.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_60 = QLabel(self.widget_2)
        self.label_60.setObjectName(u"label_60")
        self.label_60.setGeometry(QRect(282, 516, 71, 18))
        self.label_60.setFont(font)
        self.label_60.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_49 = QLabel(self.widget_2)
        self.label_49.setObjectName(u"label_49")
        self.label_49.setGeometry(QRect(402, 516, 88, 16))
        self.label_49.setMinimumSize(QSize(88, 16))
        self.label_49.setMaximumSize(QSize(88, 16777215))
        self.label_49.setFont(font)
        self.label_49.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_50 = QLabel(self.widget_2)
        self.label_50.setObjectName(u"label_50")
        self.label_50.setGeometry(QRect(702, 153, 88, 16))
        self.label_50.setMinimumSize(QSize(88, 16))
        self.label_50.setMaximumSize(QSize(88, 16777215))
        self.label_50.setFont(font)
        self.label_50.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_55 = QLabel(self.widget_2)
        self.label_55.setObjectName(u"label_55")
        self.label_55.setEnabled(False)
        self.label_55.setGeometry(QRect(700, 516, 88, 18))
        self.label_55.setMinimumSize(QSize(88, 18))
        self.label_55.setMaximumSize(QSize(88, 16777215))
        self.label_55.setFont(font)
        self.label_55.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.label_45 = QLabel(self.widget_2)
        self.label_45.setObjectName(u"label_45")
        self.label_45.setGeometry(QRect(282, 152, 91, 18))
        self.label_45.setFont(font)
        self.label_45.setStyleSheet(u"QLabel{\n"
"    background-color: transparent;\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.bench3_dw_cal = QLabel(self.widget_2)
        self.bench3_dw_cal.setObjectName(u"bench3_dw_cal")
        self.bench3_dw_cal.setGeometry(QRect(272, 435, 71, 16))
        self.bench3_dw_cal.setStyleSheet(u"background-color: rgb(0, 85, 127);")
        self.label_63_cal_2 = QLabel(self.widget_2)
        self.label_63_cal_2.setObjectName(u"label_63_cal_2")
        self.label_63_cal_2.setGeometry(QRect(213, 433, 51, 20))
        self.label_63_cal_2.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.bench4_dw_cal = QLabel(self.widget_2)
        self.bench4_dw_cal.setObjectName(u"bench4_dw_cal")
        self.bench4_dw_cal.setGeometry(QRect(272, 256, 71, 16))
        self.bench4_dw_cal.setStyleSheet(u"background-color: rgb(0, 85, 127);")
        self.label_63_cal_3 = QLabel(self.widget_2)
        self.label_63_cal_3.setObjectName(u"label_63_cal_3")
        self.label_63_cal_3.setGeometry(QRect(212, 256, 51, 20))
        self.label_63_cal_3.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.bench2_dw_cal = QLabel(self.widget_2)
        self.bench2_dw_cal.setObjectName(u"bench2_dw_cal")
        self.bench2_dw_cal.setGeometry(QRect(847, 258, 71, 16))
        self.bench2_dw_cal.setStyleSheet(u"background-color: rgb(0, 85, 127);")
        self.label_63_cal_4 = QLabel(self.widget_2)
        self.label_63_cal_4.setObjectName(u"label_63_cal_4")
        self.label_63_cal_4.setGeometry(QRect(926, 256, 51, 20))
        self.label_63_cal_4.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.bench1_dw_cal = QLabel(self.widget_2)
        self.bench1_dw_cal.setObjectName(u"bench1_dw_cal")
        self.bench1_dw_cal.setGeometry(QRect(850, 435, 71, 16))
        self.bench1_dw_cal.setStyleSheet(u"background-color: rgb(0, 85, 127);")
        self.label_63_cal_5 = QLabel(self.widget_2)
        self.label_63_cal_5.setObjectName(u"label_63_cal_5")
        self.label_63_cal_5.setGeometry(QRect(930, 433, 51, 20))
        self.label_63_cal_5.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.axis12_w_cal = QLabel(self.widget_2)
        self.axis12_w_cal.setObjectName(u"axis12_w_cal")
        self.axis12_w_cal.setGeometry(QRect(848, 346, 71, 16))
        self.axis12_w_cal.setStyleSheet(u"background-color: rgb(0, 85, 127);")
        self.label_63_cal_6 = QLabel(self.widget_2)
        self.label_63_cal_6.setObjectName(u"label_63_cal_6")
        self.label_63_cal_6.setGeometry(QRect(923, 344, 51, 20))
        self.label_63_cal_6.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.axis34_w_cal = QLabel(self.widget_2)
        self.axis34_w_cal.setObjectName(u"axis34_w_cal")
        self.axis34_w_cal.setGeometry(QRect(272, 336, 71, 16))
        self.axis34_w_cal.setStyleSheet(u"background-color: rgb(0, 85, 127);")
        self.label_63_cal_7 = QLabel(self.widget_2)
        self.label_63_cal_7.setObjectName(u"label_63_cal_7")
        self.label_63_cal_7.setGeometry(QRect(222, 336, 41, 20))
        self.label_63_cal_7.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"}")
        self.tag_1 = QLabel(self.widget_2)
        self.tag_1.setObjectName(u"tag_1")
        self.tag_1.setGeometry(QRect(1002, 496, 71, 71))
        font1 = QFont()
        font1.setFamilies([u"Adobe Fan Heiti Std"])
        font1.setPointSize(36)
        font1.setWeight(QFont.Thin)
        font1.setItalic(False)
        self.tag_1.setFont(font1)
        self.tag_1.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"	font: 100 36pt \"Adobe Fan Heiti Std\";\n"
"}")
        self.tag_2 = QLabel(self.widget_2)
        self.tag_2.setObjectName(u"tag_2")
        self.tag_2.setGeometry(QRect(1002, 136, 71, 71))
        self.tag_2.setFont(font1)
        self.tag_2.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"	font: 100 36pt \"Adobe Fan Heiti Std\";\n"
"}")
        self.tag_3 = QLabel(self.widget_2)
        self.tag_3.setObjectName(u"tag_3")
        self.tag_3.setGeometry(QRect(122, 496, 71, 71))
        self.tag_3.setFont(font1)
        self.tag_3.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"	font: 100 36pt \"Adobe Fan Heiti Std\";\n"
"}")
        self.tag_4 = QLabel(self.widget_2)
        self.tag_4.setObjectName(u"tag_4")
        self.tag_4.setGeometry(QRect(122, 136, 71, 71))
        self.tag_4.setFont(font1)
        self.tag_4.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 255, 255);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"	font: 100 36pt \"Adobe Fan Heiti Std\";\n"
"}")
        self.tag_5 = QLabel(self.widget_2)
        self.tag_5.setObjectName(u"tag_5")
        self.tag_5.setGeometry(QRect(1018, 566, 41, 31))
        font2 = QFont()
        font2.setFamilies([u"Adobe Fan Heiti Std"])
        font2.setPointSize(20)
        font2.setWeight(QFont.Thin)
        font2.setItalic(False)
        self.tag_5.setFont(font2)
        self.tag_5.setStyleSheet(u"QLabel{\n"
"    background: rgb(255, 85, 0);\n"
"    border: none;\n"
"	color: rgb(0, 0, 0);\n"
"	font: 100 20pt \"Adobe Fan Heiti Std\";\n"
"}")
        self.btn_origin = QPushButton(self.widget_2)
        self.btn_origin.setObjectName(u"btn_origin")
        self.btn_origin.setGeometry(QRect(546, 337, 101, 31))

        self.horizontalLayout.addWidget(self.widget_2)


        self.verticalLayout.addWidget(self.widget)


        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.lb_bg.setText("")
#if QT_CONFIG(whatsthis)
        self.bench4_ncj.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench4_ncj.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.bench4_zj.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench4_zj.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.l24_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.l24_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.bench2_ncj.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench2_ncj.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.bench2_zj.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench2_zj.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.w34_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.w34_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.w12_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.w12_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.bench3_zj.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench3_zj.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.bench3_ncj.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench3_ncj.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.bench1_ncj.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench1_ncj.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.bench1_zj.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench1_zj.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.l13_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.l13_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_36_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_36_cal.setText(QCoreApplication.translate("Form", u"24\u8f74\u8ddd", None))
#if QT_CONFIG(whatsthis)
        self.label_40_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_40_cal.setText(QCoreApplication.translate("Form", u"34\u5185\u6d4b\u8ddd", None))
#if QT_CONFIG(whatsthis)
        self.label_41_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_41_cal.setText(QCoreApplication.translate("Form", u"12\u5185\u6d4b\u8ddd", None))
#if QT_CONFIG(whatsthis)
        self.label_46_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_46_cal.setText(QCoreApplication.translate("Form", u"13\u8f74\u8ddd", None))
#if QT_CONFIG(whatsthis)
        self.label_44.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_44.setText(QCoreApplication.translate("Form", u"\u79f0\u91cd\u53f0\u4f4d\u79fb4", None))
#if QT_CONFIG(whatsthis)
        self.bench4_w.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench4_w.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_47.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_47.setText(QCoreApplication.translate("Form", u"\u8f6e\u91cd\u6d4b\u91cf4", None))
#if QT_CONFIG(whatsthis)
        self.label_48.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_48.setText(QCoreApplication.translate("Form", u"\u8f6e\u91cd\u6d4b\u91cf2", None))
#if QT_CONFIG(whatsthis)
        self.bench2_w.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench2_w.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_51.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_51.setText(QCoreApplication.translate("Form", u"\u8f6e\u91cd\u6d4b\u91cf3", None))
#if QT_CONFIG(whatsthis)
        self.bench3_w.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench3_w.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_52.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_52.setText(QCoreApplication.translate("Form", u"\u8f6e\u91cd\u6d4b\u91cf1", None))
#if QT_CONFIG(whatsthis)
        self.bench1_w.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.bench1_w.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_58.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_58.setText(QCoreApplication.translate("Form", u"\u5185\u4fa7\u8ddd2", None))
#if QT_CONFIG(whatsthis)
        self.label_59.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_59.setText(QCoreApplication.translate("Form", u"\u5185\u4fa7\u8ddd1", None))
#if QT_CONFIG(whatsthis)
        self.label_60.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_60.setText(QCoreApplication.translate("Form", u"\u5185\u4fa7\u8ddd3", None))
#if QT_CONFIG(whatsthis)
        self.label_49.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_49.setText(QCoreApplication.translate("Form", u"\u79f0\u91cd\u53f0\u4f4d\u79fb3", None))
#if QT_CONFIG(whatsthis)
        self.label_50.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_50.setText(QCoreApplication.translate("Form", u"\u79f0\u91cd\u53f0\u4f4d\u79fb2", None))
#if QT_CONFIG(whatsthis)
        self.label_55.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_55.setText(QCoreApplication.translate("Form", u"\u79f0\u91cd\u53f0\u4f4d\u79fb1", None))
#if QT_CONFIG(whatsthis)
        self.label_45.setWhatsThis(QCoreApplication.translate("Form", u"sensor", None))
#endif // QT_CONFIG(whatsthis)
        self.label_45.setText(QCoreApplication.translate("Form", u"\u5185\u4fa7\u8ddd4", None))
#if QT_CONFIG(whatsthis)
        self.bench3_dw_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.bench3_dw_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_63_cal_2.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_63_cal_2.setText(QCoreApplication.translate("Form", u"\u8f6e\u91cd\u5dee3", None))
#if QT_CONFIG(whatsthis)
        self.bench4_dw_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.bench4_dw_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_63_cal_3.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_63_cal_3.setText(QCoreApplication.translate("Form", u"\u8f6e\u91cd\u5dee4", None))
#if QT_CONFIG(whatsthis)
        self.bench2_dw_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.bench2_dw_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_63_cal_4.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_63_cal_4.setText(QCoreApplication.translate("Form", u"\u8f6e\u91cd\u5dee2", None))
#if QT_CONFIG(whatsthis)
        self.bench1_dw_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.bench1_dw_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_63_cal_5.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_63_cal_5.setText(QCoreApplication.translate("Form", u"\u8f6e\u91cd\u5dee1", None))
#if QT_CONFIG(whatsthis)
        self.axis12_w_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.axis12_w_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_63_cal_6.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_63_cal_6.setText(QCoreApplication.translate("Form", u"12\u8f74\u91cd", None))
#if QT_CONFIG(whatsthis)
        self.axis34_w_cal.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.axis34_w_cal.setText(QCoreApplication.translate("Form", u"-", None))
#if QT_CONFIG(whatsthis)
        self.label_63_cal_7.setWhatsThis(QCoreApplication.translate("Form", u"caled", None))
#endif // QT_CONFIG(whatsthis)
        self.label_63_cal_7.setText(QCoreApplication.translate("Form", u"34\u8f74\u91cd", None))
        self.tag_1.setText(QCoreApplication.translate("Form", u"\u2460", None))
        self.tag_2.setText(QCoreApplication.translate("Form", u"\u2461", None))
        self.tag_3.setText(QCoreApplication.translate("Form", u"\u2462", None))
        self.tag_4.setText(QCoreApplication.translate("Form", u"\u2463", None))
        self.tag_5.setText(QCoreApplication.translate("Form", u"\u9501", None))
        self.btn_origin.setText(QCoreApplication.translate("Form", u"\u8bbe\u5b9a\u539f\u70b9\u4f4d\u7f6e", None))
    # retranslateUi

