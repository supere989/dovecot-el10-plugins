FROM almalinux:10

RUN dnf -y update \
    && dnf -y install \
      git \
      gcc gcc-c++ make \
      autoconf automake libtool \
      pkgconf-pkg-config \
      which findutils \
      python3 \
      openssl-devel \
      zlib-devel \
      bzip2-devel \
      xz-devel \
      libcap-devel \
      pam-devel \
      lua lua-devel \
      gettext gettext-devel \
      bison flex \
      rpcgen \
      dnf-plugins-core \
      rpmdevtools \
      cpio \
      wget ca-certificates \
      rpm-build \
    && dnf -y clean all

WORKDIR /work

# Directory where build artifacts will be written.
RUN mkdir -p /artifacts/plugins

COPY scripts/ /work/scripts/
COPY rpm/ /work/rpm/
RUN chmod +x /work/scripts/*.sh

ENTRYPOINT ["/work/scripts/entrypoint.sh"]
