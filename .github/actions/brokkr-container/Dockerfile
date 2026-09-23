# The production guest has no Docker. No image build or pull is expected.
# This fixture's authorized result is a capability failure, not functionality.
FROM busybox:1.37.0
COPY pre.sh main.sh post.sh /
RUN chmod 0555 /pre.sh /main.sh /post.sh
