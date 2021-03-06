# athena_lambda_trigger

A Python lambda trigger to move incoming files in to correct partitioned paths on S3. It also optionally updates the Athena metadata.

Deployment can be done easily with Zappa framework when configured properly in zappa_settings.json. 

```
zappa deploy stage
```

Here is an example rules file:
```
{
  "default": {
    "athena": {
      "bucket": "my-athena-bucket",
      "prefix": "athena/lambda/"
    },
    "rules": [
      {
        "id": "Cloud Trail Example",
        "enabled": true,
        "s3": {
          "source_bucket": "my-source-bucket",
          "source_prefix": "source/",
          "target_bucket": "my-target-bucket",
          "target_prefix": "cloudtrail/",
          "partitions": ["year", "month", "day", "hour"],
          "move": false
        }
      }
    ]
  }
}
``` 
