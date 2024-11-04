FROM python:3.10

WORKDIR /app

ADD requirements.txt /app/requirements.txt

RUN pip install --upgrade pip

RUN pip install -r /app/requirements.txt

EXPOSE 443

COPY ./ /app

RUN pip config --user set global.progress_bar off

CMD ["python", "main.py"]
