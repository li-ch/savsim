from random import randrange
import simpy
import networkx as nx

import logging
from tqdm import tqdm

from router import Router
from message import SAVMechanism

if __name__=="__main__":
    env = simpy.Environment()
    logging.basicConfig(filename='savsim.log', filemode='w', format="%(levelname)s - %(message)s",level=logging.INFO)
    # format="%(asctime)s %(levelname)s - %(message)s"

    # Topology from RFC8704
    #          +----------+   P3[AS5 AS1]  +------------+
    #          | AS4(ISP4)|<---------------|  AS5(ISP5) |
    #          +----------+      (P2P)     +------------+
    #              /\   /\                        /\
    #              /     \                        /
    #  P1[AS2 AS1]/       \P2[AS3 AS1]           /
    #       (C2P)/         \(C2P)               /
    #           /           \                  /
    #    +----------+    +----------+         /
    #    | AS2(ISP2)|    | AS3(ISP3)|        /
    #    +----------+    +----------+       /
    #             /\           /\          /
    #              \           /          /
    #        P1[AS1]\         /P2[AS1]   /P3[AS1]
    #           (C2P)\       /(C2P)     /(C2P)
    #                 \     /          /
    #              +----------------+ /
    #              |  AS1(customer) |/
    #              +----------------+
    #                   P1, P2, P3 (prefixes originated)
    #
    #  Consider that data packets (sourced from AS1)
    #  may be received at AS4 with a source address
    #  in P1, P2, or P3 via any of the neighbors (AS2, AS3, AS5):
    #  * Feasible-path uRPF fails
    #  * Loose uRPF works (but not desirable)
    #  * Enhanced feasible-path uRPF works best
    topo = nx.DiGraph()
    topo.add_edge(4,5,link_type='p2p',latency=0.05)
    topo.add_edge(5,4,link_type='p2p',latency=0.05)
    topo.add_edge(2,4,link_type='c2p',latency=0.05)
    topo.add_edge(4,2,link_type='p2c',latency=0.05)
    topo.add_edge(3,4,link_type='c2p',latency=0.05)
    topo.add_edge(4,3,link_type='p2c',latency=0.05)
    topo.add_edge(1,2,link_type='c2p',latency=0.05)
    topo.add_edge(2,1,link_type='p2c',latency=0.05)
    topo.add_edge(1,3,link_type='c2p',latency=0.05)
    topo.add_edge(3,1,link_type='p2c',latency=0.05)
    topo.add_edge(1,5,link_type='c2p',latency=0.05)
    topo.add_edge(5,1,link_type='p2c',latency=0.05)

    sav = SAVMechanism.EFPuRPF_A

    router_conf = {
        1:{
            'sav': sav,
            'own_prefixes': ['p1.1', 'p1.2', 'p1.3'],
            'init_delay': 0, # randrange(1, 1000, 10)/1000, # 1~500 msec
            'export_policy' : {
                2: ['p1.1'],
                3: ['p1.2'],
                5: ['p1.3'],
            },
        },
        2:{
            'sav': sav,
            'own_prefixes': ['p2.1'],
            'init_delay': 0,
            'export_policy': {}
        },
        3:{
            'sav': sav,
            'own_prefixes': ['p3.1'],
            'init_delay': 0,
            'export_policy': {}
        },
        4:{
            'sav': sav,
            'own_prefixes': ['p4.1'],
            'init_delay': 0,
            'export_policy': {}
        },
        5:{
            'sav': sav,
            'own_prefixes': ['p5.1'],
            'init_delay': 0,
            'export_policy': {}
        }, 
    }

    # setup routers
    for n in list(topo.nodes()):
        r = Router(env,
                   topo, 
                   n, #ASN
                   router_conf[n]['sav'],
                   router_conf[n]['own_prefixes'],
                   router_conf[n]['export_policy'],
                   router_conf[n]['init_delay']
                   )
        topo.nodes[n]['router'] = r # keep the reference in graph

    # run simulation
    for i in tqdm(range(100)):
        env.run(until=i+1)
    
    # print results
    for n in topo.nodes():
        logging.info(f"==== AS{n} loc_ribs  ====")
        logging.info(topo.nodes[n]['router'].loc_ribs)
        logging.info(f"====AS{n} adj_ribs_in====")
        logging.info(topo.nodes[n]['router'].adj_ribs_in)
        logging.info(f"====AS{n} allowlist====")
        logging.info(topo.nodes[n]['router'].SAV_allowlist)