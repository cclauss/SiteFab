import os
import sys
import time
from tqdm import tqdm
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader
from termcolor import cprint

import files

from parser.parser import Parser
from Logger import Logger
from Plugins import Plugins
from PostCollections import PostCollections
from linter.linter import Linter

import utils
from utils import error

class SiteFab(object):
    """ Object representation of the site being built. 
    
    SiteFab main class 
    """

    SORT_BY_CREATION_DATE_DESC  = 1
    SORT_BY_CREATION_DATE = 2
    SORT_BY_UPDATE_DATE_DESC = 3
    SORT_BY_UPDATE_DATE = 4

    OK = 1
    SKIPPED = 2
    ERROR = 3

    def __init__(self, config_filename, version='1.0'):
        
        # Timers
        self.timings  = utils.create_objdict()
        self.timings.start = time.time()
        self.timings.init_start = time.time()
        self.current_dir = os.getcwd()

        ### configuration ###
        if not config_filename:
            raise Exception("Supply a configuration filename")

        if os.path.isfile(config_filename): #absolute path 
            self.config  = files.load_config(config_filename)
        else:
            cfg = os.path.join(files.get_site_path(), config_filename)
            if os.path.isfile(cfg):
                self.config = files.load_config(cfg)
            else:
                raise Exception("Configuration file not found: %s" % config_filename)
        
        self.config.build = utils.create_objdict()
        self.config.build.sitefab_version = version #expose sitefab version to the templates

        ### parser ###
        self.config.parser = Parser.make_config(self.config.parser) # initialize the parser config

        ### plugins ###
        plugins_config_filename = os.path.join(files.get_site_path(), self.config.plugins_configuration_file)
        plugins_config = files.load_config(plugins_config_filename)

        debug_log_fname = os.path.join(self.get_logs_dir(), "debug.log") # where to redirect the standard python log
        self.plugins = Plugins(self.get_plugins_dir(), debug_log_fname, plugins_config)
        self.plugin_data = {} # Store data generated by plugins that can be used later. 
        self.plugin_results = defaultdict(int)

        ### template rendering engine init ###
        self.jinja2 = Environment(loader=FileSystemLoader(self.get_template_dir()), extensions=['jinja2.ext.do'])
        custom_filters = self.plugins.get_template_filters()
        for flt_name, flt_fct in custom_filters.iteritems():
            self.jinja2.filters[flt_name] = flt_fct

        ### logger ###
        cfg = utils.create_objdict()
        cfg.output_dir = self.get_logs_dir()
        cfg.template_dir = os.path.join(files.get_site_path(),  self.config.logger.template_dir) #log template not the one from the users.
        cfg.log_template = "log.html"
        cfg.log_index_template = "log_index.html"
        cfg.stats_template = "stats.html"
        self.logger = Logger(cfg, self)

        ### linter ###
        linter_config_filename = os.path.join(files.get_site_path(), self.config.linter.configuration_file)
        linter_config = files.load_config(linter_config_filename)
        linter_config.report_template_file = os.path.join(files.get_site_path(), self.config.linter.report_template_file)
        linter_config.output_dir = self.get_logs_dir()
        linter_config.site_output_dir = self.get_output_dir()
        self.linter = Linter(linter_config)

        # finding content and assets
        self.filenames = utils.create_objdict()
        self.filenames.posts = files.get_files_list(self.get_content_dir(), "*.md")

        ### Cleanup the output directory ###
        files.clean_dir(self.get_output_dir())
        self.timings.init_stop = time.time()
        
    ### Engine Stages ###
    def preprocessing(self):
        "Perform pre-processing tasks"
        self.timings.preprocessing_start = time.time()
        self.execute_plugins([1], "SitePreparsing", " plugin")
        self.timings.preprocessing_stop = time.time()

    def parse(self):
        "parse md content into post objects"
        self.timings.parse_start = time.time()
        filenames = self.filenames.posts
        self.posts = []

        #collections creation
        min_posts = self.config.collections.min_posts
        
        # posts_by_tag is what is rendered. Therefore it contains for as given post both its tags and its category
        tlp = self.jinja2.get_template(self.config.collections.template)
        path = os.path.join(self.get_output_dir(), self.config.collections.output_dir)
        self.posts_by_tag = PostCollections(site=self, template=tlp, output_path=path, web_path=self.config.collections.output_dir, min_posts=min_posts)

        self.posts_by_category = PostCollections(site=self, web_path=self.config.collections.output_dir)
        self.posts_by_template = PostCollections(site=self)
        self.posts_by_microdata = PostCollections(site=self)

        
        # Parsing
        cprint("\nParsing posts", "magenta")
        progress_bar = tqdm(total=len(filenames), unit=' files', desc="Files", leave=True)
        errors = []
        post_idx = 1
        #NOTE: passing self.config.parser might seems strange but it is need as in plugin we pass other configurations.
        parser = Parser(self.config.parser, self)
        for filename in filenames:
            file_content = files.read_file(filename)
            post = parser.parse(file_content)
            post.filename = filename
            post.id = post_idx
            post_idx += 1
            # do not process hidden post
            if post.meta.hidden:
                continue
            
            # Ignore posts set for future date
            if post.meta.creation_date_ts > int(time.time()):
                s = "Post in the future - skipping %s" % (post.meta.title)
                utils.warning(s)
                continue

            self.posts.append(post)

            # insert in template list
            if not post.meta.template:
                errors += "%s has no template defined. Can't render it" % post.filename
                continue

            self.posts_by_template.add(post.meta.template, post)

            # insert in microformat list
            if post.meta.microdata_type:
                self.posts_by_microdata.add(post.meta.microdata_type, post)

            ## insert in category
            if post.meta.category:
                self.posts_by_category.add(post.meta.category, post)
                self.posts_by_tag.add(post.meta.category, post) # tags is what is rendered

            ## insert in tags
            if post.meta.tags:
                for tag in post.meta.tags:
                    self.posts_by_tag.add(tag, post)

            progress_bar.update(1)
        if len(errors):
            utils.error("\n".join(errors))

        self.timings.parse_stop = time.time()

    def process(self):
        "Processing stage"

        self.timings.process_start = time.time()
        # Posts processing
        print "\nPosts plugins"
        self.execute_plugins(self.posts, "PostProcessor", " posts")
        
        # collection processing
        print "\nCollections plugins"
        self.execute_plugins(self.posts_by_category.get_as_list(), "CollectionProcessor", " categories")
        self.execute_plugins(self.posts_by_tag.get_as_list(), "CollectionProcessor", " tags")
        self.execute_plugins(self.posts_by_template.get_as_list(), "CollectionProcessor", " templates")
        self.execute_plugins(self.posts_by_microdata.get_as_list(), "CollectionProcessor", " microdata")
        
        # site wide processing
        print "\nSite wide plugins"
        self.execute_plugins([1], "SiteProcessor", " site")
        self.timings.process_stop = time.time()

    def render(self):
        "Rendering stage"

        self.timings.render_start = time.time()
        print "\nRendering posts"
        self.render_posts()
        
        print "\nRendering collections"
        self.posts_by_tag.render()
        
        print "\nAdditional Rendering"
        self.execute_plugins([1], "SiteRendering", " pages")
        self.timings.render_stop = time.time()

    def finale(self):
        "Last stage"
        
        # Write reminainig logs
        self.logger.write_log_index()
        self.logger.write_stats()

        # Terminal recap
        cprint("Thread used:%s" % self.config.threads, "cyan")
        
        total_ts = round(time.time() - self.timings.start, 2)
        init_ts = round(self.timings.init_stop - self.timings.init_start,2)
        preprocessing_ts = round(self.timings.preprocessing_stop - self.timings.preprocessing_start,2)
        parsing_ts = round(self.timings.parse_stop - self.timings.parse_start, 2)
        processing_ts = round(self.timings.process_stop - self.timings.process_start, 2)
        rendering_ts = round(self.timings.render_stop - self.timings.render_start, 2)

        cprint("\nPerformance", 'magenta')
        cprint("|-Total Generation time: %s sec" % (total_ts,), "cyan")
        cprint("|--Init time: %s sec" % (init_ts), "blue")
        cprint("|--Preprocessing time: %s sec" % (preprocessing_ts), "blue")
        cprint("|--Parsing time: %s sec" % (parsing_ts), "blue")
        cprint("|--Processing time: %s sec" % (processing_ts), "blue")
        cprint("|--Rendering time: %s sec" % (rendering_ts), "blue")

        cprint("\nContent", 'magenta')
        cprint("|-Num posts: %s" % len(self.posts), "cyan")
        cprint("|-Num categories: %s" % self.posts_by_category.get_num_collections(), "cyan")
        cprint("|-Num tags: %s" % self.posts_by_tag.get_num_collections(), "cyan")
        cprint("|-Num templates: %s" % self.posts_by_template.get_num_collections(), "cyan")


        cprint("\nPlugins", 'magenta')
        cprint("|-Num plugins: %s" % len(self.plugins.plugins_enabled), "cyan")
        if self.plugin_results[self.ERROR]:            
            cprint("|-Num Errors:%s (check the logs!)" % self.plugin_results[self.ERROR], 'red')

        if self.plugin_results[self.SKIPPED]:
            cprint("|-Num Skipped:%s " % self.plugin_results[self.SKIPPED], 'yellow' )
        
        cprint("\nLinter", 'magenta')
        self.linter.render_report()
        if self.linter.num_post_with_errors():            
            cprint("|-Num post with errors:%s (check the logs!)" % self.linter.num_post_with_errors(), 'red')

        if self.linter.num_post_with_warnings():            
            cprint("|-Num post with warning:%s" % self.linter.num_post_with_warnings(), 'yellow')
        
        
    ### Post functions ###

    def render_posts(self):
        """Render posts using jinja2 templates."""
        for post in tqdm(self.posts, unit=' pages', miniters=1, desc="Posts"):
            template_name = "%s.html" % post.meta.template
            template = self.jinja2.get_template(template_name)
            html = post.html.decode("utf-8", 'ignore')
            rv = template.render(content=html, meta=post.meta, posts=self.posts, plugin_data=self.plugin_data, config=self.config,
            categories=self.posts_by_category.get_as_dict(), tags=self.posts_by_tag.get_as_dict(), templates=self.posts_by_template.get_as_dict(), 
            microdata=self.posts_by_microdata.get_as_dict())
            
            # Liniting            
            linter_results = self.linter.lint(post, rv, self)
            # Are we stopping on linting errors?
            if linter_results.has_errors and self.config.linter.stop_on_error:
                print post.filename
                for error in linter_results.info:
                    print "\t-%s:%s" % (error[0], error[1])
                sys.exit(-1)
            
            path = "%s%s/" % (self.get_output_dir(), post.meta.permanent_url)
            path = path.replace('//', '/')
            files.write_file(path, 'index.html', rv)
   
    ### Templates functions ###

    def get_num_templates(self):
        "Return the number of templates loaded."
        return len(self.jinja2.list_templates())

    def get_template_list(self):
        "Return the list of templates loaded."
        return self.jinja2.list_templates()


    ### Plugins ###
    def execute_plugins(self, items, plugin_class, unit):
        """ Execute a given group of plugins
        
        Args:
            items (str): list of object to apply the plugins to (either collection, posts or even None) 
            plugin_class (str):  which type of plugins to execute
            unit (str): which unit to report in the progress bar
        
        Return:
            None
        """
        results = self.plugins.run_plugins(items, plugin_class, unit, self)
        self.plugins.display_execution_results(results, self)
        
        # sum all plugins data for recap
        for result in results:
            plugin, values = result
            for k, v in values.iteritems():
                self.plugin_results[k] += v


    ### Files and directories ###
    def get_site_info(self):
        "Return site information."
        return self.site
    
    def get_config(self):
        "Return sitefab config."
        return self.config
    
    def get_output_dir(self):
        "return the absolute path of the ouput dir"
        return os.path.join(files.get_site_path(), self.config.dir.output)

    def get_content_dir(self):
        "return the absolute path of the content dir"
        return os.path.join(files.get_site_path(), self.config.dir.content)
    
    def get_template_dir(self):
        "return the absolute path of the template dir"
        return os.path.join(files.get_site_path(), self.config.dir.templates)
    
    def get_logs_dir(self):
        "return the absolute path of the template dir"
        return os.path.join(files.get_site_path(), self.config.dir.logs)
    
    def get_cache_dir(self):
        "return the absolute path of the cache dir"
        return os.path.join(files.get_site_path(), self.config.dir.cache)

    def get_plugins_dir(self):
        "return the absolute path for the plugins dir"
        return os.path.join(files.get_code_path() + "/plugins/")