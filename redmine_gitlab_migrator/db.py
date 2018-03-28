import yaml

from peewee import Model, IntegerField, CharField, ModelBase
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


def init_db():
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


def db_test():
    boards = Boards.select().where(Boards.project_id == 9)
    print(boards.sql())
    for b in boards:  # type: Boards
        print(b.id, b.project_id, b.name)


if __name__ == '__main__':
    init_db()
    db_test()