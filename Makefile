# Define variables
IMAGE_NAME = dukeman/gift-wiki
TAG = latest
PLATFORMS = linux/amd64,linux/arm64

.PHONY: env
env:
	@echo "set -a; source .env; set +a"

# Build the Docker image
build:
	docker buildx build --platform $(PLATFORMS) -t $(IMAGE_NAME):$(TAG) .

# Push the Docker image
push:
	docker buildx build --platform $(PLATFORMS) -t $(IMAGE_NAME):$(TAG) --push .

dev:
	skaffold dev

# Deploy to Kubernetes
.PHONY: deploy
deploy:
	kubectl apply -k deploy

.PHONY: clean
clean:
	kubectl delete -k deploy

# All-in-one command
all: build push deploy