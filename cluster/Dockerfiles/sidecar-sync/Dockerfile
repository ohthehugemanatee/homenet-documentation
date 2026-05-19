FROM ubuntu:20.04
RUN apt-get update && apt-get install -y dumb-init && rm -rf /var/lib/apt/lists/*
COPY ./sync-storage.sh /sync-storage.sh
RUN chmod +x /sync-storage.sh

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/sync-storage.sh"]
