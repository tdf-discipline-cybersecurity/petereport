.DEFAULT_GOAL:=help

ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

COMPOSE_PREFIX_CMD		:= COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1
ENV 					:= dev
COMPOSE_CONFIG 			:= -f docker-compose-${ENV}.yml
SERVICES 				:= nginx petereport
NO_CACHE				:= #--no-cache

# --------------------------

.PHONY: help env-backup env-build env-clean docker-build docker-up docker-down docker-stop docker-restart docker-rm docker-images

env-backup:		## Backup Environment
	${ROOT_DIR}/scripts/environment_backup.sh

env-build:		## Build Environment
	${ROOT_DIR}/scripts/environment_build.sh ${ENV}

env-clean:		## Clean Environment
	${ROOT_DIR}/scripts/environment_clean.sh

attackflow-run:	## Run local Attack Flow node server
	${ROOT_DIR}/scripts/attackflow.sh run

attackflow-build:	## Build local Attack Flow application
	${ROOT_DIR}/scripts/attackflow.sh build

attackflow-deploy:	## Deploy local Attack Flow application to Petereport directory
	${ROOT_DIR}/scripts/attackflow.sh deploy

docker-build:	## Build Docker Images
	${ROOT_DIR}/scripts/deploy_custom_files.sh deploy ${ENV}
	${COMPOSE_PREFIX_CMD} docker-compose ${COMPOSE_CONFIG} build ${NO_CACHE} ${SERVICES}
	${ROOT_DIR}/scripts/deploy_custom_files.sh undeploy ${ENV}

docker-up:		## Up Docker Containers
	${COMPOSE_PREFIX_CMD} docker-compose ${COMPOSE_CONFIG} up -d

docker-logs:	## Logs Docker Containers
	${COMPOSE_PREFIX_CMD} docker-compose ${COMPOSE_CONFIG} logs --follow --tail=1000 ${SERVICES}

docker-down	:	## Down Docker Containers
	${COMPOSE_PREFIX_CMD} docker-compose ${COMPOSE_CONFIG} down

docker-stop:	## Stop Docker Containers
	${COMPOSE_PREFIX_CMD} docker-compose ${COMPOSE_CONFIG} stop ${SERVICES}

docker-restart:	## Restart Docker Containers
	${COMPOSE_PREFIX_CMD} docker-compose ${COMPOSE_CONFIG} restart ${SERVICES}

docker-rm:		## Delete Docker Containers
	${COMPOSE_PREFIX_CMD} docker-compose ${COMPOSE_CONFIG} rm -f ${SERVICES}

docker-images:	## Show Docker images
	${COMPOSE_PREFIX_CMD} docker-compose $(COMPOSE_ALL_FILES) images ${SERVICES}

help:			## Show this help
	@echo "Manage Petereport Actions"
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m (default: help) \[\033[36m<ENV=environment>\033[0m (dev, complete, local)\]\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

debug:			# Debug
	$(info COMPOSE_CONFIG = ${COMPOSE_CONFIG})
	$(info ENV = ${ENV})
