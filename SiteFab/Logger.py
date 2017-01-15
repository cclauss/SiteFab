""" Handle SiteFab log output
"""
import time
import jinja2
import collections

from collections import defaultdict
from jinja2 import Environment, FileSystemLoader

import utils
import files
import SiteFab

class Logger():
    """ SiteFab logging system

        :note: while the logging system render log in html using jinja2 it use a completly 
        separated system to avoid interferring with user configuration. Templates are located
        in the config directory under internal_template/
    """
    def __init__(self, config, site):
        
        self.config = config
        self.site = site # reference to the main object
        self.logs = {}
        self.jinja2 = Environment(loader=FileSystemLoader(self.config.template_dir))
        files.clean_dir(self.config.output_dir)
    
    def create_log(self, category, name, filename):
        """ Create a new log
            Usually used to store a plugin output or a phase information
        """
        log = utils.dict_to_objdict()
        log.meta = utils.dict_to_objdict()
        log.events = []

        log.meta.name = name
        log.meta.category = category
        log.meta.filename = filename
        log.meta.start_time = time.time()
        log.meta.num_events = 0
        log.meta.ok = 0
        log.meta.skipped = 0
        log.meta.errors = 0
        log_id = "%s:%s" % (category, name)
        self.logs[log_id] = log
        return log_id

    def record_event(self, log_id, target, severity, details):
        """ Record a event to a given log
        """
        if log_id not in self.logs:
            return False
        
        # recording event
        event = utils.dict_to_objdict()
        event.time = time.time()
        event.target = target
        event.severity = severity
        event.details = details

        self.logs[log_id].meta.num_events += 1

        # severity
        if severity == self.site.OK:
            self.logs[log_id].meta.ok += 1
            event.severity = "OK"
        elif severity == self.site.SKIPPED:
            event.severity = "SKIPPED"
            self.logs[log_id].meta.skipped += 1
        elif severity == self.site.ERROR:
            event.severity = "ERROR"
            self.logs[log_id].meta.errors += 1

        
        self.logs[log_id].events.append(event)
        return True

    def write_log(self, log_id):
        """ Write log
        """
        if log_id not in self.logs:
            return False
        lg = self.logs[log_id]
        lg.meta.exec_time = round(time.time() - lg.meta.start_time, 2)

        template = self.jinja2.get_template(self.config.log_template)
        rv = template.render(events=lg.events, meta=lg.meta)
        files.write_file(self.config.output_dir, lg.meta.filename, rv)
        return True

    def write_log_index(self):
        " Generate the index.html file that list all generated logs"
        
        # allows to output by group
        logs = defaultdict(list)
        for l in self.logs.values():
            logs[l.meta.category].append(l)

        template = self.jinja2.get_template(self.config.log_index_template)
        rv = template.render(logs=logs)
        files.write_file(self.config.output_dir, "index.html", rv)