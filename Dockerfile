FROM public.ecr.aws/docker/library/python:3.10.13
WORKDIR /api
COPY setup.py /api
COPY main/ /api/main/
RUN python3 -m venv env
RUN . ./env/bin/activate
RUN pip3 install wheel
RUN pip3 install .
WORKDIR /api/main
EXPOSE 80
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--log-level", "info"]
