#!/bin/sh
set -eu

offset="$(od -An -N2 -tu2 /dev/urandom | tr -d '[:space:]')"
offset="$(( offset % 120 ))"
minute="$(( offset % 60 ))"
hour="$(( 12 + (offset / 60) ))"

echo "$minute $hour * * * /home/withings-sync/run-sync" >/home/withings-sync/cronjob
exec supercronic -passthrough-logs /home/withings-sync/cronjob
