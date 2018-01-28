#!/bin/sh

CMD="$(echo "$1" | tr '[:upper:]' '[:lower:]')"  # commands are case insensitive

case "$CMD" in
    help)
        echo 'Available commands:'
        echo ''
        echo 'help — this message'
        echo 'echo — try "echo", "echo some words"'
        echo 'env — dump environment; pay attention to API_PORT, API_CHAT_ID, API_USERNAME and API_USER_ID'
        echo 'date — print system date and time'
        echo 'uptime — call uptime(1)'
        echo 'empty — demo action with empty output'
        echo 'noreply — action without reply'
        echo 'rose — image'
        echo 'two — two messages in reply'
        echo 'delay — delayed reply'
        echo 'exit1 — exit with status=1; emulate error'
        echo ''
        echo 'Commands are case insensitive'
        ;;
    echo)
        echo "$@"
        ;;
    env)
        env
        ;;
    date)
        date
        ;;
    uptime)
        uptime
        ;;
    empty)
        ;;
    noreply)
        echo '.'
        ;;
    rose)
        convert rose: png:-  # just put png to stdout
        ;;
    two)
        echo 'Get the rose' |
            curl -X POST --data-binary @- "http://localhost:$API_PORT/?chat_id=$API_CHAT_ID" >/dev/null 2>&1
        convert rose: png:- |
            curl -X POST --data-binary @- "http://localhost:$API_PORT/?chat_id=$API_CHAT_ID" >/dev/null 2>&1
        echo '.'
        ;;
    delay)
        send_cmd="curl -X POST --data-binary @- 'http://localhost:$API_PORT/?chat_id=$API_CHAT_ID' >/dev/null 2>&1"
        cmd="convert rose: png:- | $send_cmd; echo 'Thanks for waiting!' | $send_cmd"
        echo "$cmd" | at -M 'now + 1 minutes' >/dev/null 2>&1
        #echo "$cmd"
        echo 'Waite 1 minute...'
        ;;
    exit1)
        echo message on stdout
        echo message on stderr >&2
        exit 1
        ;;
    *)
        echo 'Invalid command `'$CMD"'."
        echo 'Try to say `help'"'."
        ;;
esac
