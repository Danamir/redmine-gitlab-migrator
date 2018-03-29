import re

import yaml

from peewee import Model, IntegerField, CharField, ModelBase, ForeignKeyField, DateTimeField, BooleanField
from playhouse.db_url import connect

# global vars
db = None


class BaseModel(Model):
    class Meta:
        database = db
        schema = "public"


class Boards(BaseModel):
    id = IntegerField()
    project_id = IntegerField()
    name = CharField()


class Enumerations(BaseModel):
    id = IntegerField()
    name = CharField()
    type = CharField()


class Trackers(BaseModel):
    id = IntegerField()
    name = CharField()


class IssueStatuses(BaseModel):
    id = IntegerField()
    name = CharField()
    is_closed = BooleanField()
    position = IntegerField()

    # class Meta:
    #     table_name = "issue_statuses"


class Issues(BaseModel):
    id = IntegerField()
    tracker_id = IntegerField()
    subject = CharField()
    status_id = IntegerField()
    priority_id = IntegerField()

    tracker = ForeignKeyField(Trackers, backref='issues', column_name='tracker_id')
    status = ForeignKeyField(IssueStatuses, backref='issues', column_name='status_id')
    priority = ForeignKeyField(Enumerations, backref='issues', column_name='priority_id')


class Users(BaseModel):
    id = IntegerField()
    login = CharField()


class Tags(BaseModel):
    id = IntegerField()
    name = CharField()
    taggings_count = IntegerField()


class Taggings(BaseModel):
    id = IntegerField()
    tag_id = IntegerField()
    taggable_id = IntegerField()
    taggable_type = CharField()
    tagger_id = IntegerField()
    tagger_type = CharField()
    context = CharField()
    created_at = DateTimeField()

    tag = ForeignKeyField(Tags, backref='taggings', column_name='tag_id')
    issue = ForeignKeyField(Issues, backref='taggings', column_name='taggable_id')


def init_db():
    """Initialize the db and models.

    Expects configuration in ``conf.yml`` file.
    """
    global db

    # db init
    with open("conf.yml", 'r') as file:
        conf_dict = yaml.load(file)

    db_conf = conf_dict.get("db", {})
    db = connect(db_conf.get("url"))

    # bind models to database, set table names
    for k, v in globals().items():
        if isinstance(v, ModelBase) and getattr(v, "_meta", None):
            meta = getattr(v, "_meta", None)
            if meta:
                meta.database = db  # bind db

                if meta.table_name == k.lower():
                    # replace defautl table name by camel case to underscore separated
                    meta.table_name = re.sub("([a-z])([A-Z])", "\g<1>_\g<2>", k).lower()


def issue_tags(iid):
    """Get redmine issue custom tags.

    :param int iid: The issue id.
    :rtype: list[str]
    :return: The tags names, or empty list.
    """
    ret = []

    tags = Tags.select(Tags.name).join(Taggings).join(Issues).where((Taggings.taggable_type == 'Issue') & (Issues.id == iid))
    for t in tags:
        ret.append(t.name)

    return ret


def db_test():
    """Db test, dev method.
    """
    boards = Boards.select().where(Boards.project_id == 9)
    # print(boards.sql())

    for b in boards:  # type: Boards
        print(b.id, b.project_id, b.name)

    # .join(Taggings, on=((Issues.id == Taggings.taggable_id) & (Taggings.taggable_type == 'Issue')))\
    # .select(Issues.id.alias("issue_id"), Issues, Tags.id.alias("tag_id"), Tags)\

    issues = Issues\
        .select(Issues, Tags, IssueStatuses, Enumerations)\
        .join(Taggings, on=((Issues.id == Taggings.taggable_id) & (Taggings.taggable_type == 'Issue')))\
        .join(Tags)\
        .join(IssueStatuses, on=(Issues.status_id == IssueStatuses.id))\
        .join(Enumerations, on=((Issues.priority_id == Enumerations.id) & (Enumerations.type == 'IssuePriority')))\
        .where(Issues.id >= 1499)\
        .order_by(Issues.id.asc())
    print(issues.sql())

    # for rows in issues.dicts():  # type: dict
    #     print(rows)
    #     # print(str(i.id).ljust(10), i.subject, t.taggable_type)

    for i in issues:  # type: Issues
        print(i.id, i.subject)
        print(i.taggings.tag.name, i.status.name, i.priority.name)
        # print(str(i.id).ljust(10), i.subject, t.taggable_type)


if __name__ == '__main__':
    init_db()
    db_test()
    # print(issue_tags(1499))