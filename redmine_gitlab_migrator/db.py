import re

import yaml

from peewee import Model, IntegerField, CharField, ModelBase, ForeignKeyField, DateTimeField, BooleanField, JOIN, DoesNotExist
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
    is_in_chlog = BooleanField()
    position = IntegerField()
    is_in_roadmap = BooleanField()


class IssueStatuses(BaseModel):
    id = IntegerField()
    name = CharField()
    is_closed = BooleanField()
    position = IntegerField()

    # class Meta:
    #     table_name = "issue_statuses"


class IssueCategories(BaseModel):
    id = IntegerField()
    project_id = IntegerField()
    name = CharField()


class Issues(BaseModel):
    id = IntegerField()
    tracker_id = IntegerField()
    subject = CharField()
    status_id = IntegerField()
    priority_id = IntegerField()
    category_id = IntegerField()

    tracker = ForeignKeyField(Trackers, backref='issues', column_name='tracker_id')
    status = ForeignKeyField(IssueStatuses, backref='issues', column_name='status_id')
    priority = ForeignKeyField(Enumerations, backref='issues', column_name='priority_id')
    category = ForeignKeyField(IssueCategories, backref='issues', column_name='category_id')


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

    tags = Tags.select(Tags.name)\
        .join(Taggings)\
        .join(Issues)\
        .where((Taggings.taggable_type == 'Issue') & (Issues.id == iid))  # type: list[Tags]

    for t in tags:
        ret.append(t.name)

    return ret


def issue_labels(iid):
    """Get redmine issue labels extracted from tracker, status, priority, and category.

    :param int iid: The issue id.
    :rtype: (str, str, str)
    :return: Tuple of strings for tracker, status, priority, and category (category can be ``None``).
    """
    tracker, status, priority, category = None, None, None, None

    issue = Issues.select(Issues, Trackers, IssueStatuses, Enumerations, IssueCategories)\
        .join(Trackers)\
        .join(IssueStatuses, on=(Issues.status_id == IssueStatuses.id))\
        .join(Enumerations, on=((Issues.priority_id == Enumerations.id) & (Enumerations.type == 'IssuePriority')))\
        .join(IssueCategories, JOIN.LEFT_OUTER, on=(Issues.category_id == IssueCategories.id))\
        .where(Issues.id == iid)\
        .first()  # type: Issues

    if issue:
        tracker = issue.tracker.name
        status = issue.status.name
        priority = issue.priority.name
        try:
            category = issue.category.name
        except DoesNotExist:
            pass

    return tracker, status, priority, category


def project_labels(pid):
    """Get redmine project labels extracted from trackers, status, priority, and category.

    :param int pid: The project id.
    :rtype: (list[str], list[str], list[str], list[str])
    :return: Tuple of lists for trackers, statuses, priorities, and categories.
    """
    trackers = Trackers.select()  # type: list[Trackers]
    trackers = list(map(lambda x: x.name, trackers))  # type: list[str]

    statuses = IssueStatuses.select()  # type: list[IssueStatuses]
    statuses = list(map(lambda x: x.name, statuses))  # type: list[str]
    
    priorities = Enumerations.select().where(Enumerations.type == 'IssuePriority')  # type: list[Enumerations]
    priorities = list(map(lambda x: x.name, priorities))  # type: list[str]
    
    categories = IssueCategories.select().where(IssueCategories.project_id == pid)  # type: list[IssueCategories]
    categories = list(map(lambda x: x.name, categories))  # type: list[str]

    return trackers, statuses, priorities, categories


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
        .select(Issues, Tags, IssueStatuses, Enumerations, IssueCategories)\
        .join(Taggings, on=((Issues.id == Taggings.taggable_id) & (Taggings.taggable_type == 'Issue')))\
        .join(Tags)\
        .join(IssueStatuses, on=(Issues.status_id == IssueStatuses.id))\
        .join(IssueCategories, JOIN.LEFT_OUTER, on=(Issues.category_id == IssueCategories.id))\
        .join(Enumerations, on=((Issues.priority_id == Enumerations.id) & (Enumerations.type == 'IssuePriority')))\
        .where(Issues.id == 1499)\
        .order_by(Issues.id.asc())
    print(issues.sql())

    # for rows in issues.dicts():  # type: dict
    #     print(rows)
    #     # print(str(i.id).ljust(10), i.subject, t.taggable_type)

    for i in issues:  # type: Issues
        print(i.id, i.subject)
        print(i.taggings.tag.name, i.status.name, i.priority.name)
        try:
            print(i.category.name)
        except DoesNotExist:
            pass
        # print(str(i.id).ljust(10), i.subject, t.taggable_type)


if __name__ == '__main__':
    init_db()
    db_test()
    print(issue_labels(1500))
    print(project_labels(6))
    # print(issue_tags(1499))
