# Standby

Standby stops playback and releases everything that uses the network or the media server (the Plex stream, a live feed, a
web page), while the player itself keeps running. It is for overnight or while nobody is watching: a call to the web
server puts the player to sleep, and another wakes it.

```bash
curl http://<player address>:4242/player/commands/standby     # stop playing, release the network
curl http://<player address>:4242/player/commands/wake        # resume the channel that was on
```

The web remote's power button does the same thing. It reads **STANDBY** while the player is playing (press it to sleep) and turns
green and reads **WAKE** while the player sleeps (press it to resume). It follows the player's real state, so it stays right if
you use the curl calls or the cron lines below instead.

Both calls accept GET or POST. The screen goes black while in standby (switch the TV off if you like), and `/player/status`
reports `standby`. Changing the channel from the web remote also wakes the player and tunes to that channel.

Things that keep working in standby: the web server itself (so the wake call can arrive) and the schedule agent
(`schedule_agent`), which keeps topping up schedules.

Other background services are separate. The live stream picker (see [LIVE_STREAMS.md](LIVE_STREAMS.md)) only makes a few small
requests every couple of minutes; stop it with `systemctl --user stop fs42-streams` if you want it quiet too.

## On a timer

To sleep at night and wake in the morning without touching anything, add two lines to the player machine's crontab
(`crontab -e`):

```
0 1 * * *  curl -s http://localhost:4242/player/commands/standby > /dev/null
0 7 * * *  curl -s http://localhost:4242/player/commands/wake > /dev/null
```

`/player/commands/stop` still exists for anything that calls it, but it ends the player completely, and starting it again needs a
restart of the service. The web remote no longer uses it.
