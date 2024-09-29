# anomaly_base

FastAPI+MongoDB based web service for storing partitioned anomalous light curves.


# Manual

To run the anomaly base, the following steps should be performed:
1) Place the `secret_data.ini` file with this content in the project directory (on the same level as `docker-compose.yml`):
```
[NOTIF]
master_pass = <YOUR_TG_API_TOKEN>
```
and the `.env` file with the following content:
```
MONGO_INITDB_ROOT_USERNAME=<YOUR_MONGO_USERNAME>
MONGO_INITDB_ROOT_PASSWORD=<YOUR_MONGO_PASSWORD>
DATABASE_URL=mongodb://<MONGO_USERNAME>:<MONGO_USERNAME>@database:27017/
SECRET_KEY=<YOUR_SECRET_KEY>
TG_TOKEN=<YOUR_TG_API_TOKEN>
```
(I realize that duplicating TG_TOKEN -- this is strange, and will fix it in the future)

2) Create a certs folder (on the same level as the `docker-compose.yml` file), save the SSL certificates in it;
3) In the `docker-compose.yml` file, replace the paths `/home/vps/web_data`, `/home/vps/mongodata`, `/home/vps/mongobackups` and `/home/vps/anomaly_base/mongo_backup.sh` with your own.
4) Replace the domain name in this line with your own: https://github.com/fink-anomaly/anomaly_base/blob/new_design/main.py#L134.
5) Execute the commands in the project directory:
```bash
docker-compose build
docker-compose up
```
