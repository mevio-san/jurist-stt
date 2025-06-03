version := 0.0.1
component := api

echo_version:
	echo Building $(component):$(version)

image: echo_version
	docker build --tag $(component):$(version) .
