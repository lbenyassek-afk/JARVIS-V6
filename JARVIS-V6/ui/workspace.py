from pathlib import Path
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPlainTextEdit,QPushButton,QListWidget,QFileDialog,QMessageBox
from PyQt6.QtGui import QTextDocument
from PyQt6.QtPrintSupport import QPrinter
from core.workspace import records,save
from core.config import load_config

class WorkspaceDialog(QDialog):
    def __init__(self, category, parent):
        super().__init__(parent); self.category=category
        self.setWindowTitle(category); self.resize(850,650)
        layout=QVBoxLayout(self)
        self.items=QListWidget(); layout.addWidget(self.items)
        self.title=QLineEdit(); self.title.setPlaceholderText('Title / goal / research question'); layout.addWidget(self.title)
        self.body=QPlainTextEdit(); self.body.setPlaceholderText('Goals, tasks, deadlines, notes, decisions and next action'); layout.addWidget(self.body,1)
        row=QHBoxLayout(); layout.addLayout(row)
        for label, callback in [('Planning template', self.template), ('Save locally',self.persist),
                                ('Export',self.export),('Ask JARVIS',self.ask)]:
            b=QPushButton(label); b.clicked.connect(callback); row.addWidget(b)
        self.items.currentRowChanged.connect(self.select); self.refresh()
    def refresh(self):
        self.rows=records(self.category); self.items.clear(); self.items.addItems([r[1] for r in self.rows])
    def select(self,index):
        if 0<=index<len(self.rows):
            self.title.setText(self.rows[index][1]); self.body.setPlainText(self.rows[index][2])
    def persist(self):
        try: save(self.category,self.title.text() or 'Untitled',self.body.toPlainText()); self.refresh()
        except ValueError as exc: QMessageBox.warning(self,'Cannot save',str(exc))
    def template(self):
        if self.body.toPlainText().strip():
            return
        cfg=load_config(); planning=cfg.get('planning',{}); assistant=cfg.get('assistant',{})
        priorities=int(planning.get('max_daily_priorities',3))
        if self.category=='Projects':
            lines=['OUTCOME','', 'STATUS  Not started', 'DEADLINE', '', 'PRIORITIES']
            lines.extend(f'{index}. ' for index in range(1,priorities+1))
            lines.extend(['', 'NEXT ACTION', '', 'BLOCKERS / RISKS', '', 'DECISIONS'])
        elif self.category=='Life':
            lines=['DAILY FOCUS', assistant.get('daily_focus',''), '', 'TOP PRIORITIES']
            lines.extend(f'{index}. ' for index in range(1,priorities+1))
            lines.extend(['', f"FOCUS SESSION  {planning.get('focus_session_minutes',50)} minutes",
                          '', 'HEALTH / SCHOOL / PERSONAL'])
            if planning.get('daily_review', True):
                lines.extend(['', 'END-OF-DAY REVIEW'])
        else:
            lines=['OBJECTIVE', '', 'KEY FACTS', '', 'NEXT ACTION', '', 'NOTES']
        self.body.setPlainText('\n'.join(lines))
    def ask(self):
        parent=self.parent(); parent.set_chat_mode('deep_search' if self.category=='Research' else 'chat')
        parent.input.setText(f'{self.category}: {self.title.text()}\n{self.body.toPlainText()}'); self.accept(); parent.send()
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Export report','','Markdown (*.md);;PDF (*.pdf);;Word-compatible HTML (*.html)')
        if not path:return
        doc=QTextDocument(); doc.setPlainText(self.title.text()+'\n\n'+self.body.toPlainText())
        if path.lower().endswith('.pdf'):
            printer=QPrinter(); printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat); printer.setOutputFileName(path); doc.print(printer)
        else: Path(path).write_text(doc.toHtml() if path.endswith('.html') else doc.toPlainText(),encoding='utf-8')
