#!/bin/bash

# Получение текущей даты
DATE=$(date +%F_%T)

# Директория для бэкапа
BACKUP_DIR=/data/backup

# Создание директории для хранения бэкапов
mkdir -p $BACKUP_DIR

# Создание бэкапа базы данных
docker exec database mongodump --archive=$BACKUP_DIR/mongobackup_$DATE.gz --gzip --username $MONGO_INITDB_ROOT_USERNAME --password $MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase admin
