#!/bin/env python3
import argparse
import logging
import re
import sys
from calendar import monthrange
from datetime import date
from datetime import timedelta

from redmine_gitlab_migrator.redmine import RedmineProject, RedmineClient
from redmine_gitlab_migrator.gitlab import GitlabProject, GitlabClient
from redmine_gitlab_migrator.converters import convert_issue, convert_version, load_user_dict, load_user_keys
from redmine_gitlab_migrator.logger import setup_module_logging
from redmine_gitlab_migrator.wiki import TextileConverter, WikiPageConverter
from redmine_gitlab_migrator import sql
from redmine_gitlab_migrator.db import init_db, project_labels

"""Migration commands for issues and roadmaps from redmine to gitlab
"""

log = logging.getLogger(__name__)

class CommandError(Exception):
    """ An error that will nicely pop up to user and stops program
    """
    def __init__(self, msg):
        self.msg = msg


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)

    subparsers = parser.add_subparsers(dest='command')

    parser_issues = subparsers.add_parser(
        'issues', help=perform_migrate_issues.__doc__)
    parser_issues.set_defaults(func=perform_migrate_issues)

    parser_pages = subparsers.add_parser(
        'pages', help=perform_migrate_pages.__doc__)
    parser_pages.set_defaults(func=perform_migrate_pages)

    parser_roadmap = subparsers.add_parser(
        'roadmap', help=perform_migrate_roadmap.__doc__)
    parser_roadmap.set_defaults(func=perform_migrate_roadmap)

    parser_roadmap.add_argument(
        '--auto-milestones',
        required=False,
        help="Auto create milestones [monthly,yearly]")

    parser_labels = subparsers.add_parser(
        'labels', help=perform_migrate_labels.__doc__)
    parser_labels.set_defaults(func=perform_migrate_labels)

    parser_redirect = subparsers.add_parser(
        'redirect', help=perform_redirect.__doc__)
    parser_redirect.set_defaults(func=perform_redirect)

    parser_iid = subparsers.add_parser(
        'iid', help=perform_migrate_iid.__doc__)
    parser_iid.set_defaults(func=perform_migrate_iid)

    for i in (parser_issues, parser_pages, parser_roadmap, parser_labels, parser_redirect):
        i.add_argument('redmine_project_url')
        i.add_argument(
            '--redmine-key',
            required=True,
            help="Redmine administrator API key")

    for i in (parser_issues, parser_roadmap, parser_labels, parser_iid, parser_redirect):
        i.add_argument('gitlab_project_url')
        i.add_argument(
            '--gitlab-key',
            required=True,
            help="Gitlab administrator API key")

    for i in (parser_issues, parser_pages, parser_roadmap, parser_labels, parser_iid, parser_redirect):
        i.add_argument(
            '--check',
            required=False, action='store_true', default=False,
            help="do not perform any action, just check everything is ready")

        i.add_argument(
            '--debug',
            required=False, action='store_true', default=False,
            help="More output")

        i.add_argument(
            '--no-verify',
            required=False, action='store_false', default=True,
            help="disable SSL certificate verification")

    parser_issues.add_argument(
        '--closed-states',
        required=False,
        help="comma seperated list of redmine states that close an issue, default closed,rejected")

    parser_issues.add_argument(
        '--custom-fields',
        required=False,
        help="comma seperated list of redmine custom filds to migrate")

    parser_issues.add_argument(
        '--user-dict',
        required=False,
        help="file path with redmine user mapping to gitlab user, in YAML format")

    parser_issues.add_argument(
        '--user-keys',
        required=False,
        help="file path with gitlab user mapping to api key, in YAML format")

    parser_issues.add_argument(
        '--project-members-only',
        required=False, action='store_true', default=False,
        help="get project members instead of all users, useful for gitlab.com")

    parser_issues.add_argument(
        '--keep-id',
        required=False, action='store_true', default=False,
        help="create and delete empty issues for gaps, useful when no ssh is possible (e.g. gitlab.com)")

    parser_issues.add_argument(
        '--keep-title',
        required=False, action='store_true', default=False,
        help="migrate issues with same title, useful when no ssh is possible (e.g. gitlab.com) and don't need to keep id (faster)")

    parser_issues.add_argument(
        '--initial-id',
        required=False,
        help="Initial issue ID, to skip some issues")

    parser_issues.add_argument(
        '--max-id',
        required=False,
        help="Max issue ID, to skip some issues")

    parser_issues.add_argument(
        '--no-sudo', dest='sudo',
        action='store_false',
        default=True,
        help="do not use sudo, use if user is not admin (e.g. gitlab.com)")

    parser_pages.add_argument(
        '--gitlab-wiki',
        required=True,
        help="Path to local cloned copy of the GitLab Wiki's git repository")

    parser_pages.add_argument(
        '--no-history',
        action='store_true',
        default=False,
        help="do not convert the history")

    return parser.parse_args()


def check(func, message, redmine_project, gitlab_project):
    log.info('{}...'.format(message))
    ret = func(redmine_project, gitlab_project)
    if ret:
        log.info('{}... OK'.format(message))
    else:
        log.error('{}... FAILED'.format(message))
        exit(1)


def check_users(redmine_project, gitlab_project):

    redmine_users = redmine_project.get_participants()
    gitlab_users = gitlab_project.get_instance().get_all_users()

    # Filter out anonymous user
    redmine_user_names = [i['login'] for i in redmine_users if i['login'] != '']
    gitlab_user_names = set([i['username'] for i in gitlab_users])

    log.info('Redmine users are: {}'.format(', '.join(redmine_user_names) + ' '))
    log.info('GitLab users are: {}'.format(', '.join(gitlab_user_names) + ' '))

    return gitlab_project.get_instance().check_users_exist(redmine_user_names)

def check_no_issue(redmine_project, gitlab_project):
    return len(gitlab_project.get_issues()) == 0


# check_no_milestone no longer required (milestone will only be created if not exist)
#def check_no_milestone(redmine_project, gitlab_project):
#    return len(gitlab_project.get_milestones()) == 0


def check_origin_milestone(redmine_project, gitlab_project):
    return len(redmine_project.get_versions()) > 0

def perform_migrate_pages(args):
    redmine = RedmineClient(args.redmine_key, args.no_verify)
    redmine_project = RedmineProject(args.redmine_project_url, redmine)

    # Get copy of GitLab wiki repository
    wiki = WikiPageConverter(args.gitlab_wiki)

    # convert all pages including history
    pages = []
    for page in redmine_project.get_all_pages():
        print("Collecting " + page["title"])
        start_version = page["version"] if args.no_history else 1
        for version in range(start_version, page["version"]+1):
            try:
                full_page = redmine_project.get_page(page["title"], version)
                pages.append(full_page)
            except:
                log.error("Error when retrieving " + page["title"] + ", version " + str(version))

    # sort everything by date and convert
    pages.sort(key=lambda page: page["updated_on"])

    for page in pages:
        wiki.convert(page)

def perform_migrate_issues(args):
    init_db()

    closed_states = []
    if (args.closed_states):
        closed_states = args.closed_states.split(',')

    custom_fields = []
    if (args.custom_fields):
        custom_fields = args.custom_fields.split(',')

    if (args.user_dict is not None):
        load_user_dict(args.user_dict)

    if (args.user_keys is not None):
        load_user_keys(args.user_keys)

    redmine = RedmineClient(args.redmine_key, args.no_verify)
    gitlab = GitlabClient(args.gitlab_key, args.no_verify)

    redmine_project = RedmineProject(args.redmine_project_url, redmine)
    gitlab_project = GitlabProject(args.gitlab_project_url, gitlab)

    gitlab_instance = gitlab_project.get_instance()

    if (args.project_members_only):
        gitlab_users_index = gitlab_project.get_members_index()
    else:
        gitlab_users_index = gitlab_instance.get_users_index()

    redmine_users_index = redmine_project.get_users_index()
    milestones_index = gitlab_project.get_milestones_index()
    textile_converter = TextileConverter()

    log.debug('GitLab milestones are: {}'.format(', '.join(milestones_index) + ' '))

    # get issues
    log.info('Getting redmine issues')
    issues = redmine_project.get_all_issues()
    if args.initial_id:
        issues = [issue for issue in issues if int(args.initial_id) <= issue['id']]
    if args.max_id:
        issues = [issue for issue in issues if int(args.max_id) >= issue['id']]

    # convert issues
    log.info('Converting issues')
    issues_data = (
        convert_issue(args.redmine_key,
            i, redmine_users_index, gitlab_users_index, milestones_index, closed_states, custom_fields, textile_converter,
            args.keep_id or args.keep_title, args.sudo)
        for i in issues)

    # create issues
    log.info('Creating gitlab issues')
    last_iid = int(args.initial_id or 1) - 1
    for data, meta, redmine_id in issues_data:
        if args.check:
            milestone_id = data.get('milestone_id', None)
            if milestone_id:
                try:
                    gitlab_project.get_milestone_by_id(milestone_id)
                except ValueError:
                    raise CommandError(
                        "issue \"{}\" points to unknown milestone_id \"{}\". "
                        "Check that you already migrated roadmaps".format(
                            data['title'], milestone_id))

            log.info('Would create issue "{}" and {} notes.'.format(
                data['title'],
                len(meta['notes'])))

            log.info('Labels %s' % meta.get('labels', []))
            log.info('Tags %s' % meta.get('tags', []))
            log.info('Watchers %s' % meta.get('watchers', []))

        else:
            if args.keep_id:
                try:
                    fake_meta = {'uploads': [], 'notes': [], 'must_close': False}
                    if args.sudo:
                        fake_meta['sudo_user'] = meta['sudo_user']
                    while redmine_id > last_iid + 1:
                        created = gitlab_project.create_issue({'title': 'fake'}, fake_meta)
                        last_iid = created['iid']
                        gitlab_project.delete_issue(created['id'])
                        log.info('#{iid} {title}'.format(**created))
                except:
                    log.info('create issue "{}" failed'.format('fake'))
                    raise

            try:
                # labels
                for label in meta.get('labels', []):
                    gitlab_project.create_label(label)

                # tags
                for tag in meta.get('tags', []):
                    gitlab_project.create_label(tag)

                # issue
                created = gitlab_project.create_issue(data, meta)
                last_iid = created['iid']

                # watchers
                for watcher in meta.get('watchers', []):
                    created_watcher = gitlab_project.create_watcher(watcher.get('data', {}), watcher, created['iid'])

                log.info('#{iid} {title}'.format(**created))
            except:
                log.info('create issue "{}" failed'.format(data['title']))
                raise

def perform_migrate_iid(args):
    """ Should occur after the issues migration
    """

    # access gitlab database with
    # gitlab-rails dbconsole

    gitlab = GitlabClient(args.gitlab_key, args.no_verify)
    gitlab_project = GitlabProject(args.gitlab_project_url, gitlab)
    gitlab_project_id = gitlab_project.get_id()

    regex_saved_iid = r'-RM-([0-9]+)-MR-(.*)'

    sql_cmd = sql.COUNT_UNMIGRATED_ISSUES.format(
        regex=regex_saved_iid, project_id=gitlab_project_id)

    output = sql.run_query(sql_cmd)

    try:
        m = re.match(r'\s*(\d+)\s*', output, re.DOTALL | re.MULTILINE)
        issues_count = int(m.group(1))
    except (AttributeError, ValueError):
        raise ValueError(
            'Invalid output from postgres command: "{}"'.format(output))

    if issues_count > 0:
        log.info('Ready to recover iid for {} issues.'.format(
            issues_count))
    else:
        log.error(
            "No issue to migrate iid, possible causes: "
            "you already migrated iid or you haven't migrated issues yet.")
        exit(1)

    if not args.check:

        # first we change the iid to large values to prevent a
        # duplicate key value violates unique_constraint "index_issues_on_project_id_and_iid"
        # KEY (project_id, iid)=(37, 83) already exists
        sql_cmd1 = sql.UPDATE_IID_ISSUES.format(
            regex=regex_saved_iid, project_id=gitlab_project_id)
        out1 = sql.run_query(sql_cmd1)

        sql_cmd2 = sql.MIGRATE_IID_ISSUES.format(
            regex=regex_saved_iid, project_id=gitlab_project_id)
        out2 = sql.run_query(sql_cmd2)

        try:
            m = re.match(
                r'\s*(\d+)\s*', output,
                re.DOTALL | re.MULTILINE)
            migrated_count = int(m.group(1))
            log.info('Migrated successfully iid for {} issues'.format(
                migrated_count))
        except (IndexError, AttributeError):
            raise ValueError(
                'Invalid output from postgres command: "{}"'.format(output))


def perform_migrate_roadmap(args):
    redmine = RedmineClient(args.redmine_key, args.no_verify)
    gitlab = GitlabClient(args.gitlab_key, args.no_verify)

    redmine_project = RedmineProject(args.redmine_project_url, redmine)
    gitlab_project = GitlabProject(args.gitlab_project_url, gitlab)

    # auto create milestones
    milestones_data = []
    if args.auto_milestones:
        match = re.match("^(monthly|yearly):(\d{4}(-[01]\d)?)$", args.auto_milestones)
        if not match:
            log.error("--auto-milestone must be formed as (monthly|yearly):<start_date>")
            exit(1)

        milestones_type = match.group(1)
        milestones_date = list(map(lambda x: int(x), match.group(2).split("-")))

        if milestones_type == "monthly" and len(milestones_date) == 1:
            milestones_date.append(1)

        log.info("Creating %s milestones, from %s" % (milestones_type, "-".join(map(lambda x: str(x).zfill(2), milestones_date))))

        day = date(milestones_date[0], milestones_date[1], 1)
        today = date.today()

        while day <= today:
            month_days = monthrange(day.year, day.month)[1]

            milestone = {
                "title": day.strftime("%Y-%m"),
                "description": "\n\n*(auto-generated milestone)*",
                "start_date": day.strftime("%Y-%m-%d"),
                "due_date": day.replace(day=month_days).strftime("%Y-%m-%d"),
            }

            must_close = True

            if day > today - timedelta(days=4*31):  # keep last 4 months open
                must_close = False

            meta = {
                "must_close": must_close,
            }
            milestones_data.append((milestone, meta))

            # next month
            day = day + timedelta(days=month_days)

    checks = [
        #(check_no_milestone, 'Gitlab project has no pre-existing milestone'),
        (check_origin_milestone, 'Redmine project contains versions'),
    ]
    for i in checks:
        check(
            *i, redmine_project=redmine_project,
            gitlab_project=gitlab_project)

    versions = redmine_project.get_versions()
    versions_data = [convert_version(i) for i in versions]

    if milestones_data:
        versions_titles = []
        for data, meta in versions_data:
            versions_titles.append(data['title'])

        for data, meta in milestones_data:
            if data['title'] in versions_titles:
                continue

            versions_data.append((data, meta))

    for data, meta in versions_data:
        if args.check:
            log.info("Would create version {}".format(data))
        else:
            created = gitlab_project.create_milestone(data, meta)
            log.info("Version {}".format(created['title']))


def perform_migrate_labels(args):
    redmine = RedmineClient(args.redmine_key, args.no_verify)
    gitlab = GitlabClient(args.gitlab_key, args.no_verify)

    redmine_project = RedmineProject(args.redmine_project_url, redmine)
    gitlab_project = GitlabProject(args.gitlab_project_url, gitlab)

    pid = redmine_project.get_id()

    init_db()
    trackers, statuses, priorities, categories = project_labels(pid)

    labels = []

    for category in categories:
        labels.append({"name": category, 'color': "#44AD8E", 'description': category+' --'})

    for tracker in trackers:
        labels.append({"name": tracker, 'color': "#428BCA"})

    for status in statuses:
        labels.append({"name": status, 'color': "#7F8C8D"})

    for priority in priorities:
        labels.append({"name": priority, 'color': "#F0AD4E"})

    for data in labels:
        if args.check:
            log.info("Would create label {}".format(data))
        else:
            created = gitlab_project.create_label(data)
            log.info("Label {}".format(created['name']))

def perform_redirect(args):
    redmine = RedmineClient(args.redmine_key, args.no_verify)
    redmine_project = RedmineProject(args.redmine_project_url, redmine)

    # get issues
    redmine_issues = redmine_project.get_all_issues()

    print('# uncomment next line to enable RewriteEngine')
    print('# RewriteEngine On')
    print('# Redirects from {} to {}'.format(args.redmine_project_url, args.gitlab_project_url))

    for issue in redmine_issues:
        print('RedirectMatch 301 ^/issues/{}$ {}/issues/{}'.format(issue['id'], args.gitlab_project_url, issue['id']))

def main():
    args = parse_args()

    if hasattr(args, 'func'):
        if args.debug:
            loglevel = logging.DEBUG
        else:
            loglevel = logging.INFO

        # Configure global logging
        setup_module_logging('redmine_gitlab_migrator', level=loglevel)
        try:
            args.func(args)

        except CommandError as e:
            log.error(e)
            exit(12)
