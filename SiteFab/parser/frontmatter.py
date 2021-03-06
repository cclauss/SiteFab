import re
import yaml
import datetime
import time
from SiteFab import utils

date_matcher = re.compile('(\d+) +(\w{3}) +(\d+) +(\d+):(\d+)')
frontmatter_matcher = re.compile(r'(^\s*---.*?---\s*$)', re.DOTALL|re.MULTILINE)


def parse_fields(fields=None):
    """ Recursively parse a given dict of fields to add extra information (e.g timestamp) if needed
    
    Args:
        fields (dict): the fields to parse

    Returns: 
        objdict: the fields with the additional properties
    """
    if fields:
        for field_name, field_value in fields.items():
            if type(field_value) == dict:
                fields[field_name] = parse_fields(field_value)
            else:
                # adding timestamp
                if field_value and "_date" in field_name:
                    ts = parse_date_to_ts(field_value)
                    if ts:
                        fts = field_name + "_ts"
                        fields[fts] = ts
                
    return fields

def parse_date_to_ts(date_str):
    """ create the timestamp coresponding to a given date string"""
    if not date_str:
        return None
    m = date_matcher.search(date_str)
    
    if not m:
        return None
    day = m.group(1)
    month = m.group(2).capitalize()
    year = m.group(3)
    hour = m.group(4)
    minutes = m.group(5)
    
    if len(day) == 1:
        day = "0" + day

    if len(hour) == 1:
        hour = "0" + hour

    if len(minutes) == 1:
        minutes = "0" + minutes
    date_str = "%s-%s-%s %s:%s" % (day, month, year, hour, minutes)
    try:
        d = datetime.datetime.strptime( date_str, "%d-%b-%Y %H:%M" )
    except:
        return None
    dtt = d.timetuple() # time.struct_time
    ts = int(time.mktime(dtt))
    ts -= (3600 * 8) 
    return ts

def parse(post):
    """ Get a post content and extract frontmatter data if exist

    @note: all sanity check must be done via the linter and used in linter.validate()
    """
    md = post
    d = frontmatter_matcher.search(post)
    if d:
        frontmatter = d.group(1);
        md = md.replace(frontmatter, "")
        frontmatter = frontmatter.replace("---", '')
        try:
            m = yaml.load(frontmatter) #using YAML :)
        except yaml.YAMLError, exc:
            mark = exc.problem_mark
            #print "Line %s" % (mark.line+1), exc
            print "======== YAML Errors ========"
            print exc
            m =  None

        if type(m) != dict:
            meta_data = None
        else:
            meta_data = parse_fields(m)
            meta = utils.dict_to_objdict(meta_data)
    return [meta, md]
