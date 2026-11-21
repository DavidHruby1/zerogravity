# Keep the multi-platform base and APT package set fixed for repeatable builds.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 AS base

# Historical archive metadata still uses Debian's signed repository keyring.
RUN sed -i \
      -e 's|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/20261120T000000Z|' \
      -e 's|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/20261120T000000Z|' \
      -e '/^Types: deb/a Check-Valid-Until: no' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
      ca-certificates curl sudo procps sqlite3 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS ls-extractor
ARG TARGETARCH
ARG ANTIGRAVITY_BACKEND=1.18.3
WORKDIR /extract

# Pin Google's standalone archives for 1.18.3 and the APT repository packages for 1.20.6.
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) google_arch=x64 ;; \
      arm64) google_arch=arm ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    case "$ANTIGRAVITY_BACKEND" in \
      1.18.3) \
        archive_url="https://edgedl.me.gvt1.com/edgedl/release2/j0qc3/antigravity/stable/1.18.3-4739469533380608/linux-${google_arch}/Antigravity.tar.gz"; \
        app=Antigravity/resources/app; \
        case "$TARGETARCH" in \
          amd64) archive_sha=4c7fe48c954e4d255c5d3ea4c74f168a4a7187fd2beedb223423cb57481c9638 ;; \
          arm64) archive_sha=258778041c502e7ce74b39959e9b93d28f5c1d8154e553863f58a365e5a9fca5 ;; \
        esac ;; \
      1.20.6) \
        case "$TARGETARCH" in \
          amd64) \
            package=antigravity_1.20.6-1773708602_amd64_3f0d9f82447ab50374042684f891a07d.deb; \
            archive_sha=e725a5aeea575b4a74438ef48638822f7388e57e9ca1171c7d056719b3c9fd04 ;; \
          arm64) \
            package=antigravity_1.20.6-1773708612_arm64_5b7b60d8fcfc5c95ec83df02c4329f1c.deb; \
            archive_sha=d5a4d0fea158e21bba19345b98e27da130270f01a3fac6bf8823d81103747974 ;; \
        esac; \
        archive_url="https://us-central1-apt.pkg.dev/projects/antigravity-auto-updater-dev/pool/antigravity-debian/$package"; \
        app=./usr/share/antigravity/resources/app ;; \
      *) echo "Unsupported Antigravity backend: $ANTIGRAVITY_BACKEND" >&2; exit 1 ;; \
    esac; \
    language_server="$app/extensions/antigravity/bin/language_server_linux_${google_arch}"; \
    product="$app/product.json"; \
    curl --proto '=https' --proto-redir '=https' --retry 3 -fsSL "$archive_url" -o antigravity.download; \
    printf '%s  %s\n' "$archive_sha" antigravity.download | sha256sum --check; \
    case "$ANTIGRAVITY_BACKEND" in \
      1.18.3) tar -xzf antigravity.download "$language_server" "$product" ;; \
      1.20.6) \
        dpkg-deb --fsys-tarfile antigravity.download > antigravity.tar; \
        tar -xf antigravity.tar "$language_server" "$product"; \
        rm antigravity.tar ;; \
    esac; \
    install -m 0755 "$language_server" /ls_binary; \
    install -m 0644 "$product" /product.json; \
    rm -rf antigravity.download Antigravity usr

FROM base AS downloader
ARG TARGETARCH
WORKDIR /downloads

# SHA-256 values come from the v1.4.2 release asset metadata.
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) \
        release_arch=x86_64; \
        proxy_sha=eff739e9f9483064d887b9091b4ef88a8cd67a6411cb644e059a041be182e9b4; \
        cli_sha=0110cd846344e6604f206cc648451feff27be0ac5bc760b018e5ae731f3fff64; \
        library_sha=3ce9714cc75d1c7c2101406e307e3cb6b821664b23ff724aa1d6e44ec308cf30 ;; \
      arm64) \
        release_arch=arm64; \
        proxy_sha=f9b69ebf82138e51ed39cb16b5f774096f439e4a82e9a2f1083bda7fa77b1c60; \
        cli_sha=b97b994ba70a1abfb5e4292683a874337cb22d77d52401c2b238107a861b137b; \
        library_sha=f91e296db6b5584a36549745bf459d447a189d95a01a6d62be52f3f3a0e4ffc9 ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    release_url='https://github.com/NikkeTryHard/zerogravity/releases/download/v1.4.2'; \
    curl --proto '=https' --proto-redir '=https' --retry 3 -fsSL "$release_url/zerogravity-linux-${release_arch}" -o zerogravity; \
    curl --proto '=https' --proto-redir '=https' --retry 3 -fsSL "$release_url/zg-linux-${release_arch}" -o zg; \
    curl --proto '=https' --proto-redir '=https' --retry 3 -fsSL "$release_url/dns_redirect-linux-${release_arch}.so" -o dns_redirect.so; \
    printf '%s  %s\n' "$proxy_sha" zerogravity "$cli_sha" zg "$library_sha" dns_redirect.so | sha256sum --check; \
    chmod 0755 zerogravity zg

FROM base

# Create system user for UID isolation
RUN useradd --system --no-create-home --shell /usr/sbin/nologin zerogravity-ls \
    && echo "root ALL=(zerogravity-ls) NOPASSWD: ALL" > /etc/sudoers.d/zerogravity \
    && chmod 0440 /etc/sudoers.d/zerogravity

# Copy binaries
COPY --from=downloader /downloads/zerogravity /usr/local/bin/zerogravity
COPY --from=downloader /downloads/zg /usr/local/bin/zg

# Copy backend binary
COPY --from=ls-extractor /ls_binary /usr/local/bin/language_server_linux_x64

# Copy product.json so version auto-detection works (find_install_dir checks this path)
COPY --from=ls-extractor /product.json /usr/share/antigravity/resources/app/product.json

# Pre-compiled DNS redirect library — build_dns_redirect_so() detects this and skips gcc
COPY --from=downloader /downloads/dns_redirect.so /tmp/.agcache/libgthread-2.0.so.0

# Setup directories
RUN mkdir -p /root/.config/zerogravity \
    && mkdir -p /tmp/.agcache \
    && chmod 1777 /tmp/.agcache

EXPOSE 8741 443

# Accounts can be supplied in accounts.json or explicitly through the environment.
VOLUME ["/root/.config/zerogravity"]

ENV RUST_LOG=info
ENV ZEROGRAVITY_LS_PATH="/usr/local/bin/language_server_linux_x64"

ENTRYPOINT ["zerogravity"]
CMD ["--headless", "--host", "0.0.0.0", "--mitm-port", "443"]
