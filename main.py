import os
import json
import urllib.parse
import boto3
import time

print("Loading function")

s3 = boto3.client("s3")
athena_timeout = 60 * 5  # 5 minutes


def lambda_handler(event, context):
    # Get the object from the event and show its content type
    bucket_name = event["Records"][0]["s3"]["bucket"]["name"]
    object_key = urllib.parse.unquote_plus(event["Records"][0]["s3"]["object"]["key"], encoding="utf-8")

    try:
        # Find matching rule
        rule = find_rule(bucket_name, object_key)
        # Copy file
        if rule:
            response = copy_file(rule)
            if "athena" in rule:
                response = update_table_metadata(rule)
        else:
            response = f"No rule found for the file: s3://{bucket_name}/{object_key}"

        print(response)
        return response
    except Exception as e:
        print(e)
        print("Error getting object {} from bucket {}.".format(object_key, bucket_name))
        raise e


def find_rule(bucket_name, object_key):
    # Read rules file
    with open("rules.json") as f:
        rules = json.loads(f.read())

    # Get environment
    environment = os.environ.get("ENV", "default")
    if environment not in rules:
        raise Exception(f"Invalid ENV: {environment}")

    for rule in rules[environment]["rules"]:
        if rule["s3"]["source_bucket"] == bucket_name \
                and object_key.startswith(rule["s3"]["source_prefix"]) \
                and rule["enabled"]:
            rule["key"] = object_key
            rule["defaults"] = rules[environment]["athena"]
            return rule
    return None


def get_partitions_path(rule):
    params = os.path.dirname(rule["key"].replace(rule["s3"]["source_prefix"], "")).split("/")
    if len(params) != len(rule["s3"]["partitions"]):
        return None

    folders = list()
    for i in range(0, len(params)):
        folders.append(f'{rule["s3"]["partitions"][i]}={params[i]}')
    partition_path = "/".join(folders)
    return partition_path


def get_path(rule):
    partition_path = get_partitions_path(rule)
    file_name = os.path.basename(rule["key"])
    path = "/".join([rule["s3"]["target_prefix"], partition_path, file_name]).replace("//", "/")
    return path


def copy_file(rule):
    target_path = get_path(rule)
    s3_resource = boto3.resource("s3")
    s3_resource.Object(rule["s3"]["target_bucket"], target_path) \
        .copy_from(CopySource={"Bucket": rule["s3"]["source_bucket"], "Key": rule["key"]})

    if "move" in rule and rule["s3"]["move"]:
        s3_resource.Object(rule["s3"]["source_bucket"], rule["key"]).delete()


def update_table_metadata(rule):
    location = "s3://{}/{}".format(rule["s3"]["target_bucket"], os.path.dirname(get_path(rule)))
    partitions = get_partitions_path(rule).replace("/", ",")

    query = "ALTER TABLE {} ADD IF NOT EXISTS PARTITION ({}) LOCATION '{}'" \
        .format(rule["athena"]["table"], partitions, location)
    athena_query(rule["defaults"]["bucket"],
                 rule["defaults"]["prefix"],
                 rule["athena"]["database"], query)
    return query


def athena_query(athena_bucket, athena_prefix, database, query):
    session = boto3.Session()
    client = session.client("athena")

    output_location = "s3://{}/{}".format(athena_bucket, athena_prefix)
    print("Executing Athena database: {}, query:\n{}\n{}\n{}\n, output: {}".format(
        database, "-"*80, query, "-"*80, output_location))

    # Execute query
    execution = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            "Database": database
        },
        ResultConfiguration={
            "OutputLocation": output_location
        }
    )
    execution_id = execution["QueryExecutionId"]
    state = "RUNNING"

    # Wait for the result
    max_execution = athena_timeout
    while max_execution > 0 and state in ["RUNNING", "QUEUED"]:
        max_execution = max_execution - 1
        response = client.get_query_execution(QueryExecutionId=execution_id)

        if "QueryExecution" in response and \
                "Status" in response["QueryExecution"] and \
                "State" in response["QueryExecution"]["Status"]:
            state = response["QueryExecution"]["Status"]["State"]
            if state == "FAILED":
                raise Exception("Query failed: {}".format(response["QueryExecution"]))
            elif state == "SUCCEEDED":
                s3_path = response["QueryExecution"]["ResultConfiguration"]["OutputLocation"]
                return s3_path
        time.sleep(1)

    raise Exception("Query timeout")
