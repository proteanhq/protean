"""
Ray-based Engine for Protean event processing.

This module provides a simple implementation of the Protean Engine
that uses Ray for distributed event and command processing.
"""

import logging
import signal
import sys
import time
from typing import Dict, List, Optional, Type

import ray

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.utils import fqn

logger = logging.getLogger(__name__)


class Engine:
    """
    Ray-based Engine for Protean event processing.
    
    This class manages Ray actors for processing events and commands in a distributed manner.
    It is designed to be simple and robust, with good error handling.
    """
    
    def __init__(self, domain, debug: bool = False, test_mode: bool = False) -> None:
        """
        Initialize the Ray Engine.
        
        Args:
            domain: The domain object associated with the engine
            debug: Flag to enable debug logging
            test_mode: Flag to run in test mode, which processes events/commands once and shuts down
        """
        self.domain = domain
        self.debug = debug
        self.test_mode = test_mode
        self.running = False
        self.shutting_down = False
        
        # Configure logging
        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)
            
        # Initialize actors
        self._subscription_actors = {}
        self._handler_actors = {}
        self._broker_subscription_actors = {}
        
        # Initialize Ray if not already initialized
        if not ray.is_initialized():
            ray_config = self.domain.config.get("ray", {})
            ray.init(
                ignore_reinit_error=True,
                **ray_config.get("init_args", {})
            )
            logger.info("Ray initialized")
            
        # Import Ray actor implementations
        from protean.server.ray_actors import (
            SubscriptionActor,
            HandlerActor,
            BrokerSubscriptionActor
        )
        
        # Create serializable config dictionary
        # Only include the essential keys needed by actors to avoid serialization issues
        serializable_config = {
            "databases": self.domain.config.get("databases", {}),
            "event_store": self.domain.config.get("event_store", {}),
            "brokers": self.domain.config.get("brokers", {})
        }
        
        # Create handler actors for event handlers
        for handler_name, record in self.domain.registry.event_handlers.items():
            handler_cls = record.cls
            logger.debug(f"Creating handler actor for {handler_name}")
            
            try:
                # Create handler actor with serializable config
                handler_actor = HandlerActor.remote(
                    serializable_config,
                    handler_name
                )
                self._handler_actors[handler_name] = handler_actor
            except Exception as e:
                logger.error(f"Error creating handler actor for {handler_name}: {str(e)}")
                if self.debug:
                    import traceback
                    logger.error(traceback.format_exc())
        
        # Create handler actors for command handlers
        for handler_name, record in self.domain.registry.command_handlers.items():
            handler_cls = record.cls
            logger.debug(f"Creating handler actor for {handler_name}")
            
            try:
                # Create handler actor with serializable config
                handler_actor = HandlerActor.remote(
                    serializable_config,
                    handler_name
                )
                self._handler_actors[handler_name] = handler_actor
            except Exception as e:
                logger.error(f"Error creating handler actor for {handler_name}: {str(e)}")
                if self.debug:
                    import traceback
                    logger.error(traceback.format_exc())
            
        # Create subscription actors for event handlers
        for handler_name, record in self.domain.registry.event_handlers.items():
            handler_cls = record.cls
            stream_category = (
                handler_cls.meta_.stream_category
                or handler_cls.meta_.part_of.meta_.stream_category
            )
            
            logger.debug(f"Creating subscription actor for {handler_name}")
            
            try:
                # Create subscription actor with serializable config
                subscription_actor = SubscriptionActor.remote(
                    serializable_config,
                    handler_name,
                    stream_category,
                    handler_name,
                    origin_stream=handler_cls.meta_.source_stream
                )
                self._subscription_actors[handler_name] = subscription_actor
            except Exception as e:
                logger.error(f"Error creating subscription actor for {handler_name}: {str(e)}")
                if self.debug:
                    import traceback
                    logger.error(traceback.format_exc())
            
        # Create subscription actors for command handlers
        for handler_name, record in self.domain.registry.command_handlers.items():
            handler_cls = record.cls
            stream_category = f"{handler_cls.meta_.part_of.meta_.stream_category}:command"
            
            logger.debug(f"Creating subscription actor for {handler_name}")
            
            try:
                # Create subscription actor with serializable config
                subscription_actor = SubscriptionActor.remote(
                    serializable_config,
                    handler_name,
                    stream_category,
                    handler_name
                )
                self._subscription_actors[handler_name] = subscription_actor
            except Exception as e:
                logger.error(f"Error creating subscription actor for {handler_name}: {str(e)}")
                if self.debug:
                    import traceback
                    logger.error(traceback.format_exc())
            
        # Create broker subscription actors
        for subscriber_name, subscriber_record in self.domain.registry.subscribers.items():
            subscriber_cls = subscriber_record.cls
            broker_name = subscriber_cls.meta_.broker
            broker = self.domain.brokers[broker_name]
            channel = subscriber_cls.meta_.channel
            
            logger.debug(f"Creating broker subscription actor for {subscriber_name}")
            
            try:
                # Create broker subscription actor with serializable config
                broker_subscription_actor = BrokerSubscriptionActor.remote(
                    serializable_config,
                    broker_name,
                    subscriber_name,
                    channel,
                    subscriber_name
                )
                self._broker_subscription_actors[subscriber_name] = broker_subscription_actor
            except Exception as e:
                logger.error(f"Error creating broker subscription actor for {subscriber_name}: {str(e)}")
                if self.debug:
                    import traceback
                    logger.error(traceback.format_exc())
    
    def run(self) -> None:
        """
        Run the engine.
        
        This method starts all subscription actors and sets up signal handlers for graceful shutdown.
        It blocks until interrupted.
        
        In test mode, it processes all subscriptions once and then shuts down automatically.
        """
        if self.running:
            logger.warning("Engine is already running")
            return
            
        self.running = True
        self.shutting_down = False
        
        # Set up signal handlers
        self._setup_signal_handlers()
        
        try:
            logger.info("Starting Protean Engine...")
            
            # Start all subscription actors
            self._start_subscription_actors()
            
            if self.test_mode:
                logger.info("Running in test mode - will process events and exit")
                # In test mode, we just allow the engine to process what's available and shut down
                time.sleep(2)  # Give actors time to process messages
                logger.info("Test mode processing complete, shutting down")
                self.shutdown()
            else:
                # Keep the process alive until shutdown
                while not self.shutting_down:
                    time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
            self.shutdown()
            
        except Exception as e:
            logger.error(f"Error running engine: {str(e)}", exc_info=True)
            self.shutdown(exit_code=1)
            
        finally:
            logger.info("Engine stopped")
    
    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, self._handle_signal)
    
    def _handle_signal(self, sig, frame) -> None:
        """Handle termination signals."""
        logger.info(f"Received signal {sig}, shutting down...")
        self.shutdown()
    
    def _start_subscription_actors(self) -> None:
        """Start all subscription actors."""
        # Start event and command subscription actors
        for name, actor in self._subscription_actors.items():
            logger.debug(f"Starting subscription actor {name}")
            ray.get(actor.start.remote())
            
        # Start broker subscription actors
        for name, actor in self._broker_subscription_actors.items():
            logger.debug(f"Starting broker subscription actor {name}")
            ray.get(actor.start.remote())
    
    def shutdown(self, exit_code: int = 0) -> None:
        """
        Shutdown the engine gracefully.
        
        Args:
            exit_code: Exit code to return to the system
        """
        if self.shutting_down:
            return
            
        self.shutting_down = True
        self.running = False
        
        logger.info("Shutting down engine...")
        
        # Terminate all actors
        for name, actor in self._subscription_actors.items():
            logger.debug(f"Stopping subscription actor {name}")
            ray.get(actor.stop.remote())
            
        for name, actor in self._broker_subscription_actors.items():
            logger.debug(f"Stopping broker subscription actor {name}")
            ray.get(actor.stop.remote())
            
        # Shutdown Ray
        if ray.is_initialized():
            ray.shutdown()
            logger.info("Ray shutdown complete")
        
        if exit_code != 0:
            sys.exit(exit_code) 