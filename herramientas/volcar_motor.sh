#!/bin/sh
for d in /proc/[0-9]*; do
  c=$(tr '\0' ' ' < $d/cmdline 2>/dev/null)
  case "$c" in *gunicorn*) echo "== pid ${d#/proc/}: $c"; py-spy dump --pid ${d#/proc/} ;; esac
done
