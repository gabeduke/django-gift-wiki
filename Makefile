# Define variables
IMAGE_NAME = dukeman/gift-wiki
TAG = latest
PLATFORMS = linux/amd64,linux/arm64

# Build the Docker image
build:
	docker buildx build --platform $(PLATFORMS) -t $(IMAGE_NAME):$(TAG) .

# Push the Docker image
push:
	docker buildx build --platform $(PLATFORMS) -t $(IMAGE_NAME):$(TAG) --push .

# Deploy to Kubernetes
.PHONY: deploy
deploy:
	kubectl apply -k deploy

# All-in-one command
all: build push deploy