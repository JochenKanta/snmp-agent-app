import qumulo.lib.auth
import qumulo.lib.request
import qumulo.rest.fs as fs

class QumuloClient(object):
    ''' class wrapper for REST API cmd so that we can new them up in tests '''
    def __init__(self, argv=None):

        parser = argparse.ArgumentParser()
        parser.add_argument("--ip", "--host", dest="host", required=True,  help="Required: Specify host (cluster) for file lists")
        parser.add_argument("-P", "--port", type=int, dest="port", default=8000, required=False, help="specify port on cluster; defaults to 8000")
        parser.add_argument("-u", "--user", default="admin", dest="user", required=False, help="specify user credentials for login; defaults to admin")
        parser.add_argument("--pass", default="admin", dest="passwd", required=False, help="specify user pwd for login, defaults to admin")
        parser.add_argument("-b", "--buckets", type=int, default=1, dest="buckets", required=False, help="specify number of files; defaults to 1")
        parser.add_argument("-v", "--verbose", default=False, required=False, dest="verbose", help="Echo values to console; defaults to False ", action="store_true")
        parser.add_argument("start_path", action="store", help="Path on the cluster for file info; Must be the last argument")


        args = parser.parse_args()
        self.port = args.port
        self.user = args.user
        self.passwd = args.passwd
        self.host = args.host
        self.num_buckets = args.buckets
        self.verbose = args.verbose
        self.start_path = args.start_path

        self.connection = None
        self.credentials = None

        self.login()
        self.total_size = self.get_directory_size(self.start_path)
        self.max_bucket_size = self.total_size / self.num_buckets
        self.start_time = datetime.datetime.now()

        self.create_buckets()
        self.bucket_index = 0

    def login(self):
        try:
            self.connection = qumulo.lib.request.Connection(\
                                self.host, int(self.port))
            login_results, _ = qumulo.rest.auth.login(\
                    self.connection, None, self.user, self.passwd)

            self.credentials = qumulo.lib.auth.Credentials.\
                    from_login_response(login_results)
        except Exception, excpt:
            print "Error connecting to the REST server: %s" % excpt
            print __doc__
            sys.exit(1)

    def create_buckets(self):
        self.buckets = []

        if self.num_buckets == 1:
            self.buckets.append(Bucket(self.max_bucket_size, self.start_time))
        else:
            for i in range(0, self.num_buckets):
                self.buckets.append(Bucket(self.max_bucket_size, self.start_time))

    def current_bucket(self):
        return self.buckets[self.bucket_index]

    def save_current_bucket(self):
        # save the bucket and move to the next one
        self.buckets[self.bucket_index].save(self.bucket_index, len(self.start_path))

        if self.verbose:
            print "--------Dumping Bucket: " + str(self.bucket_index) + "-------------"
            self.buckets[self.bucket_index].print_contents()

    def get_next_bucket(self):
        # Only increment to a new bucket if we are not already pointing to the
        # last one
        self.save_current_bucket()

        if self.bucket_index < len(self.buckets) -1:
            self.bucket_index +=1

    def get_directory_size(self, path):
        try:
            result = fs.read_dir_aggregates(self.connection, self.credentials,
                                            path=path)
        except qumulo.lib.request.RequestError, excpt:
            print "Error: %s" % excpt
            sys.exit(1)

        return int(result.data['total_capacity'])

    def process_folder(self, path):

        response = fs.read_entire_directory(self.connection, self.credentials,
                                            page_size=5000, path=path)
        for r in response:
            self.process_folder_contents(r.data['files'], path)

    def process_folder_contents(self, dir_contents, path):


        for entry in dir_contents:
            size = 0
            if entry['type'] != "FS_FILE_TYPE_DIRECTORY":
                size = int(entry['size'])
            else:
                size = self.get_directory_size(entry['path'])

            # File or dir fits in the current bucket -> add it
            if size <= self.current_bucket().remaining_capacity():
                self.current_bucket().add(entry, path, size)
            # This item is too large to fit in the bucket.
            # Check if it is a dir and traverse it.
            # We can pick some files within in
            elif (entry['type'] == "FS_FILE_TYPE_DIRECTORY"):
                new_path = path + entry['name'] + "/"
                self.process_folder(new_path)
            # Don't leave an empty bucket.
            elif self.current_bucket().bucket_count() == 0:
               self.current_bucket().add(entry, path, size)
            #Out of space in the current bucket and this is a file
            #Create a new bucket and add the item to it
            else:
                print "Filled bucket " + str(self.bucket_index)
                self.get_next_bucket()
                self.current_bucket().add(entry, path, size)

        # save the last bucket
        self.save_current_bucket()