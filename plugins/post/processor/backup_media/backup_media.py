from tqdm import tqdm
from multiprocessing import Pool
import requests
import os

import urlparse

from SiteFab.Plugins import PostProcessor
from SiteFab.SiteFab import SiteFab
from SiteFab import files


def download(info):
    #adapter = SSLAdapter('TLSv1')
    #s = requests.Session()
    #s.mount('https://', adapter)
    url = info[0].replace("https://www.elie.net/", "http://elie-www.appspot.com/").replace("https:", "http:")
    if 'https:' in url or 'http:' in url:
        path = info[1]
        fname = info[2]
        r = requests.get(url, verify=False)
        if r.status_code == 200:
            files.write_file(path,fname, r.content, binary=True)
            return [True, url]
        else:
            return [False, url]
    else:
        return [False, url]


class BackupMedia(PostProcessor):
    def process(self, post, site, config):
        if post.md and len(post.md):
            p = Pool(5)  # num thread
            path = os.path.join(files.get_site_path(), config.backup_dir)
            path_post = post.meta.permanent_url.split('/')[-1]
            to_dl = []

            # # banner
            if post.meta.banner:
                banner = urlparse.urlparse(post.meta.banner)
                extension = banner.path[-4:]
                banner_name = "%s%s" % (path_post, extension)
                local_path = os.path.join(path, "banner/")
                to_dl.append((post.meta.banner, local_path, banner_name))

            # # images
            for img in post.elements.images:
                a = urlparse.urlparse(img)
                fname = os.path.basename(a.path)
                local_path = os.path.join(path, "images/", path_post)
                to_dl.append((img, local_path, fname))
            # files
            if post.meta.files:
                for f in post.meta.files.values():
                    a = urlparse.urlparse(f)
                    fname = os.path.basename(a.path)
                    local_path = os.path.join(path, "files/", path_post)
                    to_dl.append((f, local_path, fname))
            progress_bar = tqdm(total=len(to_dl), unit=' files', desc="Files to dl", leave=False)

            log = ""
            for result in p.imap_unordered(download, to_dl):
            #for i in to_dl:
                #result = download(i)
                progress_bar.update(1)
                if not result:
                    log += "Failed download - %s<br>" % (result[1]) 
                else:
                    log += "Saved - %s<br>"  % (result[1])
            p.close()
            p.join()

            return (SiteFab.OK, post.meta.title, log)
        else:
            return (SiteFab.SKIPPED, post.meta.title, "")