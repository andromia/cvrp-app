![Python application](https://github.com/christopherpryer/cvrp-app/workflows/Python%20application/badge.svg)

# cvrp-app
Development projcet for solving the cvrp problem via containerized microservices & a restful API implementation.

# objectives

- redevelop the [cvrp-app](https://github.com/christopherpryer/cvrp-app) for production-grade requirements
- learn to utilize [Vagrant](https://www.vagrantup.com/) for standard linux development environments
- learn to utilize [docker](https://www.docker.com/)
- build a deployable prototype in python to get going
- refator and optimize using c++
- lean on and learn to contribute to [or-tools](https://github.com/google/or-tools)
- dive deeper into numpy utilization & custom optimizations
- deploy to [DO](https://www.digitalocean.com/)
- complete as modular service for future projects

# development

Initial development will be monolithic type until services can be abstracted. For the meantime use the following process:

1. Test with instance/app.db
2. use init.sh for initial database migrations

# demo

add instance/app.db & create database (if it doesn't exist)
```cmd/bash
mkdir instance
touch instance/app.db
python manage.py db create_all
```

add .env file or set environment variables yourself
```.env
FLASK_APP=app
FLASK_ENV=development
FLASK_DEBUG=1 # not needed
```

:rocket: launch
```cmd/bash
python manage.py runserver
```

![](https://github.com/christopherpryer/cvrp-app/blob/master/docs/img/v0.0.1.PNG?raw=true)
