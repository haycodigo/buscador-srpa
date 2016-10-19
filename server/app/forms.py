#!/usr/bin/env python
# -*- coding: utf-8 -*-
from flask.ext.wtf import Form
from wtforms import validators, IntegerField, TextAreaField, BooleanField, SelectField
from flask_wtf.file import FileField, FileRequired, FileAllowed
from flask_user.translations import lazy_gettext as _
from models import MAX_TEXT_LENGTH, Question, Report, Topic, SubTopic, Author, Answerer
import time
import datetime
from helpers import SpreadSheetReader
from flask import render_template, redirect, url_for


def get_or_create(session, model, **kwargs):
    """ Imita el get_or_create de django
        URL: http://stackoverflow.com/questions/2546207/does-sqlalchemy-have-an-equivalent-of-djangos-get-or-create
    """
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance.id
    else:
        instance = model(**kwargs)
        session.add(instance)
        session.commit()
        return instance.id


class QuestionForm(Form):
    number = IntegerField(
        _('Question number'),
        [validators.NumberRange(min=1, message=_('Question number must be a \
                                                  positive integer'))]
    )
    body = TextAreaField(
        _('Question body'),
        [validators.Length(min=1, max=MAX_TEXT_LENGTH)]
    )
    justification = TextAreaField(
        _('Question justification (optional)'),
        [validators.Length(min=0, max=MAX_TEXT_LENGTH)]
    )
    context = TextAreaField(
        _('Question context (optional)'),
        [validators.Length(min=0, max=MAX_TEXT_LENGTH)]
    )
    answerer = TextAreaField(
        _('Question answerer'),
        [validators.Length(min=0, max=MAX_TEXT_LENGTH)]
    )
    report = TextAreaField(
        _('Report number'),
        [validators.Length(min=0, max=MAX_TEXT_LENGTH)]
    )
    author = TextAreaField(
        _('Question author'),
        [validators.Length(min=0, max=MAX_TEXT_LENGTH)]
    )
    topic = TextAreaField(
        _('Question topic'),
        [validators.Length(min=0, max=MAX_TEXT_LENGTH)]
    )
    subtopic = TextAreaField(
        _('Question subtopic'),
        [validators.Length(min=0, max=MAX_TEXT_LENGTH)]
    )

    def save_question(self, db_session):
        #  TODO> Le agrego una fecha a mano aca para que no tire error.
        report_id = get_or_create(db_session, Report, name=self.report.data, date=datetime.date(2999, 9, 9))
        author_id = get_or_create(db_session, Author, name=self.author.data)
        topic_id = get_or_create(db_session, Topic, name=self.topic.data)
        subtopic_id = get_or_create(db_session, SubTopic, name=self.subtopic.data)
        question = Question(
            number=self.number.data,
            body=self.body.data,
            justification=self.justification.data,
            context=self.context.data,
            answerer=None,  # TODO: incorporar answerers que es many-to-many
            report_id=report_id,
            author_id=author_id,
            topic_id=topic_id,
            subtopic_id=subtopic_id
        )
        db_session.add(question)
        db_session.commit()
        return question

    def handle_request(self, db_session, searcher):
        if self.validate_on_submit():
            question = self.save_question(db_session)
            searcher.restart_text_classifier()
            return redirect(url_for('see_question', question_id=question.id))
        return render_template('forms/single_question_form.html', question_form=self)


class UploadForm(Form):
    spreadsheet = FileField(
        'spreadsheet',
        validators=[FileRequired(), FileAllowed(['xls', 'xlsx', 'csv'], 'Spreadsheets only (.xsl, .xslx, .csv)')]
    )

    def save_spreadsheet(self):
        original_filename = self.spreadsheet.data.filename
        new_filename = str(int(time.time())) + '.' + original_filename.split('.')[-1]
        self.spreadsheet.data.save('app/uploads/' + new_filename)
        return new_filename

    def handle_request(self):
        if self.validate_on_submit():
            filename = self.save_spreadsheet()
            return redirect(url_for('process_spreadsheet', filename=filename))
        return render_template('forms/question_upload_form.html', upload_form=self)


class ProcessSpreadsheetForm(Form):
    discard_first_row = BooleanField(_('First row is header'), [validators.DataRequired()])
    number = SelectField(_('Question number'), [validators.DataRequired()])
    body = SelectField(_('Question body'), [validators.DataRequired()])
    justification = SelectField(_('Question justification'))
    context = SelectField(_('Question context'))
    answerer = SelectField(_('Question answerer'))
    report = SelectField(_('Report number'))
    author = SelectField(_('Question author'))
    topic = SelectField(_('Question topic'))
    subtopic = SelectField(_('Question subtopic'))
    # keywords ?

    def handle_request(self, filename, db_session, searcher):
        spreadsheet_summary = SpreadSheetReader.first_read(filename)
        self.update_choices(spreadsheet_summary['first_row'])
        if self.validate_on_submit():
            self.save_models(filename, db_session)
            searcher.restart_text_classifier()
            return redirect(url_for('home_page'))
        return render_template(
            'forms/process_spreadsheet.html',
            filename=filename,
            spreadsheet_summary=spreadsheet_summary,
            process_spreadsheet_form=self
        )

    def update_choices(self, first_row):
        choices = [(str(i), first_row[i]) for i in range(len(first_row))]
        choices = [('', _('None'))] + choices
        self.number.choices = choices
        self.body.choices = choices
        self.justification.choices = choices
        self.context.choices = choices
        self.answerer.choices = choices
        self.report.choices = choices
        self.author.choices = choices
        self.topic.choices = choices
        self.subtopic.choices = choices

    def save_models(self, filename, db_session):
        columns = self._collect_columns()
        extension = filename.split('.')[-1]
        with open('app/uploads/' + filename, 'rb') as spreadsheet_file:

            if extension == 'csv':
                spreadsheet = SpreadSheetReader.read_csv(spreadsheet_file)
            # TODO: leer xls y xlsx

            for i, row in spreadsheet:
                if i == 0 and self.discard_first_row.data:
                    continue
                args = self.collect_args(row, columns)
                question = Question(**args)
                db_session.add(question)
            db_session.commit()

    def _collect_columns(self):
        columns = [
            (self.number.data, 'number'),
            (self.body.data, 'body'),
            (self.justification.data, 'justification'),
            (self.context.data, 'context'),
            (self.answerer.data, 'answerer'),
            (self.report.data, 'report'),
            (self.author.data, 'author'),
            (self.topic.data, 'topic'),
            (self.subtopic.data, 'subtopic')
        ]
        return [(int(tuple[0]), tuple[1]) for tuple in columns if len(tuple[0]) > 0]

    @staticmethod
    def collect_args(row, columns):
        d = {}
        for col in columns:
            position = col[0]
            if position < len(row):
                value = row[col[0]].strip()
            else:
                value = ''
            d[col[1]] = value
        return d


class FullTextQueryForm(Form):
    main_text = TextAreaField(
        _('Base text to query'),
        [validators.Length(min=1, max=200)]
    )

    def handle_request(self):
        if self.validate_on_submit():
            return redirect(url_for('search', q=self.main_text.data))
        return render_template('forms/full_text_query.html', form=self)