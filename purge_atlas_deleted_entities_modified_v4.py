######Added logging and kerberos authentication check 

import requests
import getpass
import json
import subprocess
import time
import os
import logging
from datetime import datetime, date, timedelta
import sys
import argparse
from datetime import datetime, date


# Setting up logging
log_date = date.today().strftime("%Y-%m-%d")
output_log_handler = logging.FileHandler(filename="/data/logs/atlas-purge/purge_output_{}.log".format(log_date), mode='a')
error_log_handler = logging.FileHandler(filename="/data/logs/atlas-purge/purge_error_{}.log".format(log_date), mode='a')
error_log_handler.setLevel(logging.ERROR)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(output_log_handler)
root_logger.addHandler(error_log_handler)

def prompt_credentials():
    nbkid = 'username'
#    nbkid = 'username'
    kinit_command = 'kinit -kt /keytab/path/username.keytab username@domain.com'
#    kinit_command = 'kinit -kt /keytab/path/username.keytab username@domain.com'
    subprocess.call(kinit_command, shell=True)
    password = ''
    return nbkid, password


def check_kerberos_authentication():
    try:
        process = subprocess.Popen(['klist'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        if process.returncode == 0:
            root_logger.info(stdout)
        else:
            root_logger.error("Kerberos Authentication Failed: " + stderr)
            sys.exit(1)
    except Exception as e:
        root_logger.error("Kerberos Authentication Failed: " + str(e))
        sys.exit(1)

# Call the function at the start of the script
check_kerberos_authentication()


def check_active_host(nbkid, password, atlas_hosts):
    active_host = None
    for host in atlas_hosts:
        try:
            response = requests.get(host + '/api/atlas/admin/status', auth=(nbkid, ''))
            if response.json().get('Status') == 'ACTIVE':
                active_host = host
                break
        except requests.exceptions.RequestException:
            continue
    return active_host

def getCurrTime():
    return '\n[' + datetime.now().strftime("%H:%M:%S.%f") + ']:'


def prompt_cluster():
    cluster = str('Enter cluster name: ')

def prompt_user_time():
    user_time = str(raw_input('Enter a time (in format YYYY-MM-DD): '))

def prompt_total_entities_count_for_purge():
    total_entities_to_purge = int(input('Total number of entities you wish to purge in this run: '))

    user_input = input("Enter the batch size [default: 5000]: ")
    batch_size_per_iteration = int(user_input) if user_input else 5000

    if total_entities_to_purge == 0 or batch_size_per_iteration == 0:
        logging.info('Invalid input')
        exit()
		
return total_entities_to_purge, batch_size_per_iteration

def get_deleted_entities(offset, atlas_host_name, nbkid, password, total_entities_to_delete, atlas_hosts):
    deleted_entities_str = ""
    atlas_host_name = check_active_host(nbkid, password, atlas_hosts)
    url = "{}/api/atlas/v2/search/basic".format(atlas_host_name)
    data = {
        'excludeDeletedEntities': False,
        'entityFilters': {
            'condition': 'AND',
            'criterion': [
                {
                    'attributeName': '__state',
                    'operator': 'eq',
                    'attributeValue': 'DELETED'
                }
            ]
        },
        'attributes': [
            'guid,__state'
        ],
        'limit': total_entities_to_delete,
        'offset': offset,
        'typeName': 'hive_table'
    }

	current_time_now = datetime.now()
    current_time = current_time_now.strftime("%Y-%m-%d %H:%M:%S")
    logging.info(current_time)

    count_url = "curl -i -L --negotiate -u:{} -k --retry 5 --retry-delay 1 '{}/api/atlas/discovery/search/dsl?typeName=hive_table&query=from+hive_table+select+count()'".format(nbkid,atlas_host_name)
    count_output = subprocessaaaa.check_output(count_url, shell=True)
    count_output = count_output.decode('utf-8')
    count_separator = 'Transfer-Encoding: chunked'
    if count_separator not in count_output:
        logging.info("Error: Expected separator string not found in HTTP response")
        return
    headers, body = count_output.split(count_separator, 1)
    json_str_count = count_output.split('\n')[-1]
    count_data = json.loads(json_str_count)
    total_count_guids = count_data['results'][0]['count()']
    logging.info("Number of GUIDS ==> {}". format(total_count_guids))
	

	data_string = json.dumps(data)

    curl_command = """curl -i -L --negotiate -u:username -k -X POST {} -H 'Content-Type: application/json' -d '{}' """.format(url, data_string)

    try:
        deleted_entities = subprocess.check_output(curl_command, shell=True)
#        logging.info(deleted_entities)
        separator = 'Transfer-Encoding: chunked'
        if separator not in deleted_entities:
            logging.info("Error: Expected separator string not found in HTTP response")
            return
        headers, body = deleted_entities.split(separator, 1)
        deleted_entities_str = body.decode("utf-8")
        deleted_entities_dict = json.loads(deleted_entities_str)
    except ValueError:
        logging.info("Could not decode the following as JSONS: {}".format(deleted_entities_str))
        raise

    return deleted_entities_dict



def save_extracted_guids(deleted_entities, file_path):
    if not deleted_entities or 'entities' not in deleted_entities:
        return
    with open(file_path, 'w') as f:
        for entity in deleted_entities['entities']:
            guid = entity['guid']
            status = entity['status']
            
            if status == "DELETED":
                f.write(guid + '\n')

def split_file_into_batches(file_path, batch_size):
    batches = []
    current_batch = []

    with open(file_path, "r") as source_file:
        for line in source_file:
            current_batch.append(line.strip())

            if len(current_batch) == batch_size:
                batches.append(current_batch)
                current_batch = []

        # Add any remaining lines to the last batch
        if current_batch:
            batches.append(current_batch)

    return batches

def purge_deleted_entities(batches, atlas_host_name, nbkid, password, atlas_hosts):
    atlas_host_name = check_active_host(nbkid, password, atlas_hosts)
    url_purge = "{}/api/atlas/admin/purge/".format(atlas_host_name)

    def run_cmd(batch):
        cmd = "curl -L --negotiate -u:username -k -X PUT {2} -H 'Content-Type: application/json' -d '{3}'".format(nbkid, password, url_purge, json.dumps(batch))
        logging.info(cmd)
        subprocess.call(cmd, shell=True, stdout=open(os.devnull, 'wb'), stderr=open(os.devnull, 'wb'))
    # Loop through each batch and call run_cmd to purge the entities
    for batch in batches:
        run_cmd(batch)

def get_deleted_typeName_count(atlas_host_name, nbkid, password, typeName):
    atlas_host_name = check_active_host(nbkid, password, atlas_hosts)
    url = "{}/api/atlas/v2/search/quick".format(atlas_host_name)
    headers = {
        'Content-Type': 'application/json'
    }

	data = {
        'excludeDeletedEntities': False,
        'includeSubClassifications': False,
        'includeSubTypes': False,
        'includeClassificationAttributes': False,
        'entityFilters': {
            'condition': 'AND',
            'criterion': [

                {
                "attributeName":"__timestamp",
                "operator":"lt",
                "attributeValue": milliseconds
                },

                {
                    'attributeName': '__state',
                    'operator': 'eq',
                    'attributeValue': 'DELETED'
                }
            ]
        },
        'tagFilters': None,
        'attributes': [
            '__modificationTimestamp',
            '__timestamp'
        ],
        'limit': 1,
        'offset': 0,
        'typeName': typeName,
        'classification': None,
        'termName': None
    }

    command = [
        'curl', '-i', '-L', '--negotiate', '-u:username', '-k', '-X', 'PUT', '-H', 'Content-Type: application/json', '-d', json.dumps(data), url
    ]

	response = subprocess.run(command, capture_output=True, text=True)
    response_json = response.json(response.stdout)
    total_count = int(response_json["aggregationMetrics"]["__typeName"][0]["count"])
    logging.info(getCurrTime(), "The total", typeName, "counts which are in deleted state:", total_count)
    return total_count

def main(full_option, nbkid=None, password=None, total_entities_to_purge=None, batch_size_per_iteration=None, cluster=None, user_time=None):
    orig_time = datetime.strptime(user_time, "%Y-%m-%d")

    est_offset = timedelta(hours=-5)
    est_time = orig_time + est_offset

    linux_time = int(time.mktime(est_time.timetuple()))

    milliseconds = linux_time * 1000



	if cluster == 'CLUSTER1':
            atlas_hosts = ['https://CLUSTER11.domain.com:31443', 'https://CLUSTER12.domain.com:31443']
    elif cluster == 'CLUSTER2':
            atlas_hosts = ['https://CLUSTER21.domain.com:31443', 'https://CLUSTER22.domain.com:31443']
    elif cluster == 'CLUSTER3':
            atlas_hosts = ['https://CLUSTER31.domain.com:31443', 'https://CLUSTER32.domain.com:31443']
    elif cluster == 'CLUSTER4':
            atlas_hosts = ['https://CLUSTER41.sdi.domain.com:31443', 'https://CLUSTER42.sdi.domain.com:31443']
    
                            #Capturing the active atlas host

    active_host = None

	for host in atlas_hosts:
            try:
                    response = requests.get(host + '/api/atlas/admin/status', auth=(nbkid, ''))
                    with open('/data/logs/atlas-purge/atlas-response.text', 'w') as f:
                            f.write(response.text)
                    with open('/data/logs/atlas-purge/atlas-response.text', 'r') as f:
                            content = f.read()
                            logging.info("Currently checking {} is active or passive".format(host))
                            logging.info(content)
                    if content == '{"Status":"ACTIVE"}':
                            active_host = host
                            atlas_host_name = host
#                            logging.info(host)
                            break
            except requests.exceptions.RequestException as e:
                    logging.info("Error access Atlas host")
####

    file_path = '/data/logs/atlas-purge/initial_extracted_guids.txt'
    batch_size_in_each_purge_rest_call = 200

    if not nbkid or not password:
        nbkid, password = prompt_credentials()

    if not full_option:
        if total_entities_to_purge is None or batch_size_per_iteration is None:
            total_entities_to_purge, batch_size_per_iteration = prompt_total_entities_count_for_purge()
    else:
        if total_entities_to_purge is None:
        total_entities_to_purge = get_deleted_typeName_count(atlas_host_name, nbkid, password, 'hive_table')
        if batch_size_per_iteration is None:
        batch_size_per_iteration = 5000

    logging.info("Purging {} entities in batches of {}".format(total_entities_to_purge,batch_size_per_iteration))

    # Calculate the number of iterations required
    num_iterations = (total_entities_to_purge + batch_size_per_iteration - 1) // batch_size_per_iteration
    logging.info("{} Total Iterations: {}".format(getCurrTime(), num_iterations))

    # Loop through the number of iterations
    for iter in range(num_iterations):
        start_index = iter * batch_size_per_iteration
        end_index = min(start_index + batch_size_per_iteration - 1, total_entities_to_purge)

        logging.info("{} Purging entity. From index: {}, To Index: {}".format(getCurrTime(), start_index, end_index))

        total_entities_to_purge_per_iteration = batch_size_per_iteration
        if iter == (num_iterations - 1):
            total_entities_to_purge_per_iteration = total_entities_to_purge - (iter * batch_size_per_iteration)

        deleted_entities_json = get_deleted_entities(start_index, atlas_host_name, nbkid, password,total_entities_to_purge_per_iteration, atlas_hosts)
        save_extracted_guids(deleted_entities_json, file_path)

        batches = split_file_into_batches(file_path, batch_size_in_each_purge_rest_call)
        purge_deleted_entities(batches, atlas_host_name, nbkid, password, atlas_hosts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument('-f', '--full', action='store_true', help='Executing a purge operation on all deleted hive_tables in Atlas, disregarding the values of total_entities_to_purge and batch_size_per_iteration')
    parser.add_argument('total_entities_to_purge', nargs='?', type=int, default=None, help='The total count of entities that need to be purged')
    parser.add_argument('batch_size_per_iteration', nargs='?', type=int, default=None, help='Batch size per iteration refers to the number of guids fetched from Atlas in each iteration.')
    parser.add_argument('cluster', default=None, help='Name of the cluster - like CLUSTER1,CLUSTER2,CLUSTER3,CLUSTER4')
    parser.add_argument('user_time', default=None, help='Enter a time (in format YYYY-MM-DD)')

    args = parser.parse_args()

    if args.full:
        main(args.full, None, None, None, None, args.cluster)
    else:
        main(args.full, None, None, args.total_entities_to_purge, args.batch_size_per_iteration, args.cluster, args.user_time)
		
# Function to delete log files older than a given number of days
def delete_old_log_files(directory, prefix, suffix, days):
    current_time = time.time()
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        # Check if the file matches the given pattern
        if filename.startswith(prefix) and filename.endswith(suffix):
            file_creation_time = os.path.getctime(file_path)
            # Check if the file is older than the given number of days
            if (current_time - file_creation_time) > (days * 86400):
                try:
                    os.remove(file_path)
                    logging.info("Deleted old log file: {}".format(file_path))
                except Exception, e:
                    logging.error("Error deleting file {}. Error: {}".format(file_path, e))

# Deleting log files older than 7 days
delete_old_log_files("/data/logs/atlas-purge/", "purge_output_", ".log", 7)
delete_old_log_files("/data/logs/atlas-purge/", "purge_error_", ".log", 7)

