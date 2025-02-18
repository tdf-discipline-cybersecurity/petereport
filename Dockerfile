FROM debian:stable-slim

# Set environment variables
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

# No apt prompts
ARG DEBIAN_FRONTEND=noninteractive

# Fetch package list
RUN apt -y update
RUN apt -y upgrade

# Make sure locale is set to UTF-8
RUN apt-get install -y locales locales-all
ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8

# Install dependencies
RUN apt -y install texlive-latex-recommended texlive-fonts-extra texlive-latex-extra p7zip-full texlive-xetex
RUN apt -y install python3-minimal python3-pypandoc
RUN apt -y install libpangocairo-1.0-0
RUN apt -y install python3-distutils
RUN apt -y install pipenv
RUN apt -y purge python3-gunicorn gunicorn pandoc

ARG TARGETARCH

# Install pandoc and pandoc-crossref
#RUN apt -y install cabal-install ghc pkg-config
#RUN cabal v2-update
#RUN cabal v2-install --install-method=copy pandoc-cli pandoc-crossref
#RUN apt -y purge cabal-install ghc pkg-config
#RUN rm -rf ~/.ghc ~/.cabal/lib ~/.cabal/packages ~/.cabal/share
#ENV PATH="$PATH:$HOME/.cabal/bin"
ARG PANDOC_VERSION=3.6.2
ARG PANDOC_CROSSREF_VERSION=v0.3.18.1a
ADD https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${TARGETARCH}.deb ./
ADD https://github.com/lierdakil/pandoc-crossref/releases/download/${PANDOC_CROSSREF_VERSION}/pandoc-crossref-Linux-X64.tar.xz ./
RUN ls -l pandoc-${PANDOC_VERSION}-1-${TARGETARCH}.deb
RUN dpkg -i pandoc-${PANDOC_VERSION}-1-${TARGETARCH}.deb && rm -f pandoc-${PANDOC_VERSION}-1-${TARGETARCH}.deb
RUN tar -xf pandoc-crossref-Linux-X64.tar.xz && \
    mv pandoc-crossref /usr/local/bin/ && \
    chmod a+x /usr/local/bin/pandoc-crossref && \
    mkdir -p /usr/local/man/man1 && \
    mv pandoc-crossref.1  /usr/local/man/man1

ENV OSFONTDIR=/usr/share/fonts
RUN fc-cache --really-force --verbose

WORKDIR /opt/petereport

RUN python3 --version

COPY Pipfile ./
RUN pipenv install --deploy --ignore-pipfile --python 3.11

# Final Debian Update
RUN apt -y update
RUN apt -y upgrade
RUN apt -y clean
RUN apt -y autoremove