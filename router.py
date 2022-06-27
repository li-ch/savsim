import simpy
from collections import defaultdict
import networkx as nx
import logging

from message import BGPAnnouncement, SAVMechanism, SAVNETMessage


class Router(object):
    """
        Parameters
        ----------
        own_prefix: list
            a list of strings. Each string is a prefix. It can be as simple as 'p1', but more specific prefix is also allowed. For example, IPv4 prefixes has the form "x.x.x.x/x". 
    """
    def __init__(self, 
                 env: simpy.Environment,
                 topo: nx.Graph,
                 asn: int,   
                 sav_mechanism: SAVMechanism, 
                 own_prefix: list,
                 export_policy: dict,
                 init_delay: float=0.01) -> None:
        logging.info(f"time:{env.now:.4f} Creating AS{asn}")
        self.ASN = asn
        self.env = env
        self.topo = topo
        self.store = simpy.Store(env)
        self.init_delay = init_delay

        # lists of AS numbers
        self.total_num_interface = 0
        self.customers = {}
        self.providers = {}
        self.peers = {}
        self.neighbors = [] # information is duplicated here
        self.interface_to_neighbors = {} # interface_id -> neighbor's ASN
        # topo is a digraph to preserve link type between nodes
        # assign interfaces locally with the information in topo
        for nbr in list(topo.neighbors(self.ASN)):
            if topo[self.ASN][nbr]["link_type"] == "p2p":
                self.peers[nbr] = {
                    'asn':nbr, 
                    'interface':self.total_num_interface
                    }
                self.neighbors.append({
                    'asn':nbr, 
                    'type':'peer', 
                    'interface':self.total_num_interface})
                self.interface_to_neighbors[self.total_num_interface] = nbr
                logging.info(f"time:{env.now:.4f} AS{nbr} added as peer to AS{asn} on interface {self.total_num_interface}")
                self.total_num_interface += 1
            
            elif topo[self.ASN][nbr]["link_type"] == "c2p":
                self.providers[nbr] = {
                    'asn':nbr, 
                    'interface':self.total_num_interface
                    }
                self.neighbors.append({
                    'asn':nbr, 
                    'type':'provider', 
                    'interface':self.total_num_interface})
                self.interface_to_neighbors[self.total_num_interface] = nbr
                logging.info(f"time:{env.now:.4f} AS{nbr} added as provider to AS{asn} on interface {self.total_num_interface}")
                self.total_num_interface += 1
            
            elif topo[self.ASN][nbr]["link_type"] == "p2c":
                self.customers[nbr] = {
                    'asn':nbr, 
                    'interface':self.total_num_interface
                    }
                self.neighbors.append({
                    'asn':nbr, 
                    'type':'customer', 
                    'interface':self.total_num_interface})
                self.interface_to_neighbors[self.total_num_interface] = nbr
                logging.info(f"time:{env.now:.4f} AS{nbr} added as customer to AS{asn} on interface {self.total_num_interface}")
                self.total_num_interface += 1
            
            else:
                logging.error(f"time:{env.now:.4f} AS{nbr}-{topo[self.ASN][nbr]['link_type']} is not a valid link type.")
        
        self.adj_ribs_in = defaultdict(list)
        self.prefix_origins = defaultdict(set) # prefix -> set of AS
        self.adj_ribs_out = defaultdict(list)
        # loc_ribs only have one best route for each prefix
        self.loc_ribs = {}

        self.local_prefixes = own_prefix
        for p in self.local_prefixes:
            # loc_ribs only have one best route for each prefix
            self.loc_ribs[p] = [self.ASN] 
            logging.info(f"time:{env.now:.4f} AS{self.ASN} local RIB updated with prefix {p}-{self.loc_ribs[p]}")

            self.adj_ribs_in[p].append([self.ASN])
            logging.info(f"time:{env.now:.4f} AS{self.ASN} adjRIBin added prefix {p}-AS{[self.ASN]}")

            self.prefix_origins[p].add(self.ASN)
            logging.info(f"time:{env.now:.4f} AS{self.ASN} prefix origins added prefix {p}-AS{self.ASN}")

            self.adj_ribs_out[p].append([self.ASN])
            logging.info(f"time:{env.now:.4f} AS{self.ASN} adjRIBout added prefix {p}-{[self.ASN]}")

        self.export_policy = export_policy

        self.SAV = sav_mechanism
        self.SAV_allowlist = defaultdict(set) # ASN -> allowed prefix
        
        # Tracks total message sent
        self.total_send = 0

        self.action = env.process(self.run())

    def run(self):
        # on init, wait and do full broadcast
        yield self.env.timeout(self.init_delay)
        logging.info(f"time:{self.env.now:.4f} AS{self.ASN} starts running")
        self.bgp_broadcast(full=True)
        # for each message, do a selective broadcast when necessary
        while True:
            msg = yield self.store.get()
            self.handle_message(msg)        

    def put(self, msg):
        self.store.put(msg)

    def handle_message(self, msg):
        # forward message to correct handler
        logging.info(f"time:{self.env.now:.4f} AS{self.ASN} receives {msg}")
        if isinstance(msg, BGPAnnouncement):
            self.handle_BGP_message(msg)
        elif isinstance(msg, SAVNETMessage):
            self.handle_SAVENT_message(msg)
        else:
            logging.error(f"time:{self.env.now:.4f} Unsupported message type {type(msg)}.")
        
    def handle_BGP_message(self, msg: BGPAnnouncement):    
        # update adj_ribs_in
        new_paths = defaultdict(list)
        
        # check if the message contains new path for current prefix
        for prefix, received_path_list in msg.payload.items():
            logging.info(f"time:{self.env.now:.4f} AS{self.ASN} processing prefix {prefix}")
            for received_path in received_path_list:
                logging.info(f"time:{self.env.now:.4f} AS{self.ASN} processing prefix {prefix} with path {received_path}")
                got_new_path = True 
                for existing_path in self.adj_ribs_in[prefix]:
                    if received_path == existing_path:
                        if got_new_path:
                            got_new_path = False
                            break # goto next received path
                if got_new_path:
                    logging.info(f"time:{self.env.now:.4f} AS{self.ASN} found new path for {prefix}: {received_path}")
                    new_paths[prefix].append(received_path)
                    # update adj_ribs_in
                    self.adj_ribs_in[prefix].append(received_path)
                    # update prefix origins
                    self.prefix_origins[prefix].add(received_path[0])
        
        if len(new_paths.keys())>0:
        # update loc_ribs: shorter path wins
            for prefix, paths_list in new_paths.items():
                if prefix not in self.loc_ribs:
                    self.loc_ribs[prefix] = paths_list[0]
                for path in paths_list:
                    if len(self.loc_ribs[prefix])>len(path):
                        self.loc_ribs[prefix] = path
        # send announcement
        ## two strategies: send all new information vs send only loc_ribs
        ## we first implement send all new
        ## todo: allow users to choose using router_config
            self.adj_ribs_out = new_paths
            self.bgp_broadcast(full=False)
            # flush ribs_out
            self.adj_ribs_out = defaultdict(list)
        
        # update RPF for every new bgp message
        self.updateRPF()

    def send_message(self, dst, msg):
        # filter with BGP export policy
        if isinstance(msg, BGPAnnouncement):
            if len(self.export_policy) > 0:
                filtered_payload = {}
                if dst in self.export_policy.keys():
                    allowed_prefix_list = self.export_policy[dst]
                    for allowed_prefix in allowed_prefix_list:
                        if allowed_prefix in msg.payload.keys():
                            filtered_payload[allowed_prefix] = msg.payload[allowed_prefix]
                filtered_message = BGPAnnouncement(
                    msg.node_id,
                    msg.message_id,
                    filtered_payload)
                logging.info(f"time:{self.env.now:.4f} AS{self.ASN} original payload: {msg.payload}")
                logging.info(f"time:{self.env.now:.4f} AS{self.ASN} filtered payload: {filtered_payload}")
                msg = filtered_message
            # do nothing if there's no export policy (permissive)
        
        latency = 1.0*self.topo[self.ASN][dst]['latency']
        logging.info(f"time:{self.env.now:.4f} AS{self.ASN} sends to AS{dst}: {msg}")
        yield self.env.timeout(latency)
        self.topo.nodes[dst]['router'].put(msg)

    def bgp_broadcast(self, full=True):
        for nbr in self.neighbors:
            nasn = nbr['asn']
            payload = defaultdict(list)
            if full: # during initialization, send loc_ribs
                for prefix, as_path in self.loc_ribs.items():
                    if prefix in self.local_prefixes:
                        new_path = [self.ASN]
                        payload[prefix].append(new_path)
                    elif nasn not in as_path: # external prefix
                        new_path = [self.ASN, *as_path]
                        payload[prefix].append(new_path)
            else: # normal operation, only send information in adj_ribs_out
                for prefix, as_paths_list in self.adj_ribs_out.items():
                    for as_path in as_paths_list:
                        if prefix in self.local_prefixes:
                            new_path = [self.ASN]
                            payload[prefix].append(new_path)
                        elif nasn not in as_path: # external prefix
                            new_path = [self.ASN, *as_path]
                            payload[prefix].append(new_path)
            if len(payload.keys()) > 0:
                self.total_send +=1
                msg = BGPAnnouncement(self.ASN, f"{self.ASN}-{self.total_send}", payload)
                # must be registered process to yield, otherwise wont know who to schedule
                self.env.process(self.send_message(nasn,msg)) 
    
    def updateRPF(self):
        logging.info(f"time:{self.env.now:.4f} AS{self.ASN} updates RPF")
        if self.SAV == SAVMechanism.EFPuRPF_A:
            logging.info(f"time:{self.env.now:.4f} AS{self.ASN} uses EFPuRPF-A")
            self.EFP_uRPF_A()
        elif self.SAV == SAVMechanism.EFPuRPF_B:
            logging.info(f"time:{self.env.now:.4f} AS{self.ASN} uses EFPuRPF-B")
            self.EFP_uRPF_B()
        else:
            logging.warning(f"time:{self.env.now:.4f} AS{self.ASN} uses {self.SAV} (unavailable)")

    def EFP_uRPF_A(self):
        # https://www.rfc-editor.org/rfc/rfc8704.txt
        # 1.  Create the set of unique origin ASes considering only the routes
        #     in the Adj-RIBs-In of customer interfaces.  Call it Set A = {AS1,
        #     AS2, ..., ASn}.
        # 2.  Considering all routes in Adj-RIBs-In for all interfaces
        #     (customer, lateral peer, and transit provider), form the set of
        #     unique prefixes that have a common origin AS1.  Call it Set X1.
        SetA = set() # set of all ASes from customers
        SetXs = defaultdict(set) # AS number -> set of prefixes originates from it.
        # logging.info(f"time:{self.env.now:.4f} AS{self.ASN} adjRIBsin: {self.adj_ribs_in}")
        for prefix, paths_list in self.adj_ribs_in.items():
            logging.info(f"time:{self.env.now:.4f} AS{self.ASN} prefix: {prefix}, {paths_list}")
            for path in paths_list:
                for asn in path:
                    if asn in self.customers.keys():
                        SetA.add(asn)
                    SetXs[asn].add(prefix)
        # logging.info(f"time:{self.env.now:.4f} AS{self.ASN} updates set A and Xs")
        logging.info(f"time:{self.env.now:.4f} AS{self.ASN} has customers:{self.customers} A-{SetA} Xs-{SetXs}")
                    
        # 3.  Include Set X1 in the RPF list on all customer interfaces on
        #     which one or more of the prefixes in Set X1 were received.
        for a in list(SetA): # SetXs.keys():
            Xa = SetXs[a] # SetXs[a] is the set of unique prefixes that have a common origin AS-a (Xa)
            logging.info(f"time:{self.env.now:.4f} AS{self.ASN} Xa:{Xa}")
            for prefix in list(Xa):
                originating_ases = self.prefix_origins[prefix] # the ASes that have sent this prefix to the current AS
                logging.info(f"time:{self.env.now:.4f} AS{self.ASN} originating_ases for prefix {prefix} are {originating_ases}")

                for asn in list(originating_ases):
                    if asn in self.customers.keys():
                        customer_interface = self.customers[asn]['interface']
                        self.SAV_allowlist[customer_interface] = self.SAV_allowlist[customer_interface].union(Xa)
        # 4.  Repeat Steps 2 and 3 for each of the remaining ASes in Set A
        #     (i.e., for ASi, where i = 2, ..., n).
        logging.info(f"time:{self.env.now:.4f} AS{self.ASN} updates allowlists {self.SAV_allowlist}")

    def handle_SAVNET_message(self, msg):
        logging.info(f"time:{self.env.now:.4f} AS{self.ASN} to send SAVNET message")