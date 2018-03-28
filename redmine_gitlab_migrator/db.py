import yaml

from peewee import Model, IntegerField, CharField, ModelBase, ForeignKeyField, DateTimeField
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


class Trackers(BaseModel):
    id = IntegerField()
    name = CharField()


class Issues(BaseModel):
    id = IntegerField()
    tracker_id = IntegerField()
    subject = CharField()

    tracker = ForeignKeyField(Trackers, backref='issues', column_name='tracker_id')


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

    # bind models to database
    for k, v in globals().items():
        if isinstance(v, ModelBase) and getattr(v, "_meta", None):
            meta = getattr(v, "_meta", None)
            if meta:
                meta.database = db


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
        .select(Issues, Tags)\
        .join(Taggings)\
        .join(Tags)\
        .where(Issues.id >= 1499)\
        .where(Taggings.taggable_type == 'Issue')\
        .order_by(Issues.id.asc())
    print(issues.sql())

    for rows in issues.dicts():  # type: dict
        print(rows)
        # print(str(i.id).ljust(10), i.subject, t.taggable_type)

    for i in issues:  # type: Issues
        print(i)
        print(i.taggings.tag.name)
        # print(str(i.id).ljust(10), i.subject, t.taggable_type)


if __name__ == '__main__':
    init_db()
    # db_test()
    print(issue_tags(1499))