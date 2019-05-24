import os
import sys
from argparse import ArgumentParser
import protean


class ManagementUtility:
    """
    Protean Command Line Utility
    """
    def __init__(self, argv):
        self.argv = argv or sys.argv[:]

    def execute(self):
        """
        Parsing the command and execute them
        """
        prog_name = self.argv[0]
        subcommand = self.argv[1]
        parser = ArgumentParser(
            prog='%s %s' % (os.path.basename(prog_name), subcommand)
        )
        self.add_arguments(parser)
        options = parser.parse_args(self.argv[2:])
        cmd_options = vars(options)
        args = cmd_options.pop('args', ())
        self.handle(**cmd_options)
        return parser

    def handle(self, **options):
        """ Create Template folder logic goes here """
        print(options)
        project_name = options.pop('domain')
        base_name = '%s_name' % project_name
        cache = options.pop('cache')
        template_dir = os.path.join(protean.__path__[0], 'templates')
        # for root, dirs, files in os.walk(template_dir):
        return None

    def add_arguments(self, parser):
        """ Add arguments """

        parser.add_argument('domain', help='Name of the application or project.')
        parser.add_argument('--cache', nargs='?', help='Enable Redis?')
        parser.add_argument('--db', nargs='?', help='Postgres')


def execute_from_command_line(argv=None):
    """Run a ManagementUtility."""
    utility = ManagementUtility(argv)
    utility.execute()
