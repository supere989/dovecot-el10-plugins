FROM docker.io/almalinux:10.2

RUN dnf -y install dnf-plugins-core \
    && dnf config-manager --set-enabled crb \
    && dnf -y install \
      git \
      gcc gcc-c++ make \
      autoconf automake libtool \
      pkgconf-pkg-config \
      which findutils \
      python3 python3-pytest \
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
      rpm-build binutils patch diffutils shadow-utils util-linux \
    && dnf -y clean all

# Project-specific rootless devbox. Mount source read-only at /project,
# keep build trees in /work, and write reviewable outputs to /artifacts.
WORKDIR /project
ENTRYPOINT ["bash", "/project/scripts/entrypoint.sh"]
