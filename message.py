from enum import Enum

class SAVMechanism(Enum):
    STRICTuRPF = 0
    LOOSEuRPF = 1
    FPuRPF = 2
    EFPuRPF_A = 3
    EFPuRPF_B = 4
    SAVNET = 5

class Message(object):
    def __init__(self, node_id, msg_id: str) -> None:
        self.node_id = node_id
        self.message_id = msg_id

class BGPAnnouncement(Message):
    """ Message type of BGP route announcements

        Parameters
        ----------
        msg_id: str
            the message unique id (for debugging)
        paylaod: dict
            the content of the message. Keys are prefixes, and values are AS path.
    """
    def __init__(self, node_id, msg_id, payload) -> None:
        super().__init__(node_id, msg_id)
        self.payload = payload

    def __repr__(self) -> str:
        return f"(origin:AS{self.node_id}, msg_id:{self.message_id}, payload:{self.payload})"

class SAVNETMessage(Message):
    def __init__(self, node_id, msg_id: str) -> None:
        super().__init__(node_id, msg_id)
