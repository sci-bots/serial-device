'''
Wait on multiple :class:`threading.Event` instances.

Based on code from: https://stackoverflow.com/questions/12317940/python-threading-can-i-sleep-on-two-threading-events-simultaneously/12320352#12320352
'''
import threading


def or_set(self):
    self._set()
    self.changed()


def or_clear(self):
    self._clear()
    self.changed()


def orify(event, changed_callback):
    '''
    Override ``set`` and ``clear`` methods on event to call specified callback
    function after performing default behaviour.

    Parameters
    ----------

    '''
    event.changed = changed_callback
    if not hasattr(event, '_set'):
        # `set`/`clear` methods have not been overridden on event yet.
        # Override methods to call `changed_callback` after performing default
        # action.
        event._set = event.set
        event._clear = event.clear
        event.set = lambda: or_set(event)
        event.clear = lambda: or_clear(event)


def OrEvent(*events):
    '''
    Parameters
    ----------
    events : list(threading.Event)
        List of events.

    Returns
    -------
    threading.Event
        Event that is set when **at least one** of the events in :data:`events`
        is set.
    '''
    or_event = threading.Event()

    def changed():
        '''
        Set ``or_event`` if any of the specified events have been set.
        '''
        bools = [event_i.is_set() for event_i in events]
        if any(bools):
            or_event.set()
        else:
            or_event.clear()
    for event_i in events:
        # Override ``set`` and ``clear`` methods on event to update state of
        # `or_event` after performing default behaviour.
        orify(event_i, changed)

    # Set initial state of `or_event`.
    changed()
    return or_event
