FROM python:3.10

WORKDIR /app

ADD requirements.txt /app/requirements.txt

RUN pip install --upgrade pip

RUN pip install -r /app/requirements.txt

RUN pip uninstall bson pymongo -y

RUN pip install pymongo==4.6.0

EXPOSE 8080

COPY ./ /app

RUN pip config --user set global.progress_bar off

CMD ["python", "main.py"]
