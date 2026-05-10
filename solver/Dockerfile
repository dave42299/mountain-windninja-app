# WindNinja solver container -- PLACEHOLDER (not currently used)
#
# For Phase 2, the backend invokes the solver via settings.solver_image
# (defaults to "mountain-windninja:local"), which is the upstream image
# pulled and tagged during Phase 1:
#
#   docker pull --platform linux/amd64 ghcr.io/austfi/mountain-windninja:3.12.2
#   docker tag ghcr.io/austfi/mountain-windninja:3.12.2 mountain-windninja:local
#
# This Dockerfile exists for Phase 4+ when we need a custom solver image.
# Known requirements for a custom build:
#
# - The upstream image lacks the public HRRR pastcast patch. If historical
#   reanalysis (PASTCAST-HRRR) is needed, the build must apply
#   docker/patch_windninja_public_pastcast.py from the mountain_windninja
#   repo to src/ninja/gcp_wx_init.cpp before compiling.
#
# - Any app-specific scripts (config generation, output postprocessing)
#   should be copied into /opt/windninja/scripts/ below.

FROM ghcr.io/austfi/mountain-windninja:3.12.2

WORKDIR /opt/windninja

COPY scripts/ /opt/windninja/scripts/
