| Note |
|:-|
| I freeze this project and I do not plan to continue to develop it. Instead of it I start [new one](https://github.com/michurin/instant-bot). It is the extendable Telegram bot too with very similar basic ideas: (i) all logic lies on separate user script, (ii) auto recognising text/images, (iii) local HTTP server to send asynchronious messages, etc. The new bot writen on Node.js. I beleave that Node.js is more sutable for such asynchronious network applications. You can get more information and examples on the [project page](https://github.com/michurin/instant-bot) right now. |

Telegram bot for system monitoring and administration
=====================================================

Telegram bot for monitoring and remote system control.

Project status
--------------

Proof of concept. Suitable for home use.

Key features
------------

* Simple one-file script. Implements Telegram bot API.
* All bot logic lives in *user script*. You can use any language and tools to implement it. Cast a look at `example.sh`.
* Can pass *text messages* and *images*.
* Support async messages (no replies only).

Dependencies
------------

* Python 2.7
* [Twisted](http://twistedmatrix.com/)

Quick start
-----------

* Install Python and Twisted
* Contact [BotFather](https://telegram.me/BotFather) and create new bot
* `git clone` this project souce
* Edit `mbot.ini`: `secret`, yout bot `id`, add yourself to `allowed_usernames`
* Run `mbot.py`
* Run Telegram client, find your Bot. Say `/start` to bot.
* Edit `slave.sh` to plya with your own bot commands.

Advanced use
------------

You can find all exampes in [`example.sh`](example.sh).

TODO/Misfeatures
----------------

* I use python `logging`. It's not good with Twisted. But I love it :-)
