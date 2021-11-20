FROM ubuntu:20.04
RUN apt update && apt install dumb-init -y && rm -rf /var/lib/apt/lists/*
ADD ./sync-storage.sh /sync-storage.sh
RUN chmod +x /sync-storage.sh

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/sync-storage.sh"]
