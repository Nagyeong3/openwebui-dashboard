"""Cooperative controls checked at safe request and publication boundaries."""
class JobPaused(Exception):
    pass

class JobCancelled(Exception):
    pass

class ControlledClient:
    def __init__(self, client, check):
        self.client, self.check = client, check
    def __getattr__(self, name):
        target = getattr(self.client, name)
        if not callable(target):
            return target
        def call(*args, **kwargs):
            self.check()
            result = target(*args, **kwargs)
            # A model response must be saved before honouring a pause.
            if name != 'classify':
                self.check()
            return result
        return call
