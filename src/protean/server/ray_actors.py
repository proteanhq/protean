"""
Ray actor implementations for Protean's event processing system.

This module provides Ray actor implementations for subscriptions, event handlers, and command handlers.
These actors can be distributed across a Ray cluster for parallel processing of events and commands.
All implementations use simple, non-async code for easier maintenance.
"""

import importlib
import logging
import time
from typing import Any, Dict, List, Optional, Type, Union

import ray

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.utils.mixins import Message
from protean.utils.globals import g, current_domain
from protean.utils import fqn

logger = logging.getLogger(__name__)


@ray.remote
class SubscriptionActor:
    """Ray actor implementation of a subscription.
    
    This actor polls the event store for new events/commands and processes them
    by sending them to the appropriate handler actors.
    """
    
    def __init__(
        self,
        domain_config: Dict,
        subscriber_id: str,
        stream_category: str,
        handler_cls_name: str,
        messages_per_tick: int = 10,
        position_update_interval: int = 10,
        origin_stream: Optional[str] = None,
        tick_interval: float = 1.0,
    ) -> None:
        """Initialize the SubscriptionActor.
        
        Args:
            domain_config: The domain configuration (simplified serializable version)
            subscriber_id: Unique identifier for the subscriber
            stream_category: The category of stream to subscribe to
            handler_cls_name: Fully qualified name of the handler class
            messages_per_tick: Number of messages to process per tick
            position_update_interval: Interval to update subscription position
            origin_stream: Optional origin stream to filter messages
            tick_interval: Interval between polling ticks in seconds
        """
        self.domain_config = domain_config
        self.subscriber_id = subscriber_id
        self.stream_category = stream_category
        self.handler_cls_name = handler_cls_name
        self.messages_per_tick = messages_per_tick
        self.position_update_interval = position_update_interval
        self.origin_stream = origin_stream
        self.tick_interval = tick_interval
        
        self.current_position = -1
        self.messages_since_last_position_write = 0
        self.subscriber_stream_name = f"position-{subscriber_id}"
        
        # Control flags
        self.running = False
        
        # Import the domain and handler class
        try:
            module_name, class_name = self.handler_cls_name.rsplit(".", 1)
            module = importlib.import_module(module_name)
            self.handler_cls = getattr(module, class_name)
            
            # Set up the event store connection
            self._domain = None
            self._event_store = None
            self._handler_actor = None
            
            # Initialize connections
            self._initialize()
        except Exception as e:
            logger.error(f"Error initializing SubscriptionActor for {subscriber_id}: {str(e)}", exc_info=True)
            self.handler_cls = None
            self._domain = None
            self._event_store = None
            self._handler_actor = None
    
    def _initialize(self) -> None:
        """Initialize connections to the domain and event store."""
        try:
            # Import Domain dynamically to avoid circular imports
            from protean.domain import Domain
            
            # Create a domain instance with the configuration
            self._domain = Domain("subscription", config=self.domain_config)
            
            # Initialize the domain
            self._domain.init()
            
            # Get the event store
            self._event_store = self._domain.event_store.store
            
            # Get a reference to the handler actor
            self._handler_actor = ray.get_actor(f"handler_{self.handler_cls_name}")
            
            logger.debug(f"Subscription {self.subscriber_id} initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing subscription {self.subscriber_id}: {str(e)}", exc_info=True)
            self._domain = None
            self._event_store = None
            self._handler_actor = None
    
    def start(self) -> None:
        """Start the subscription polling process."""
        if self.running:
            logger.warning(f"Subscription {self.subscriber_id} is already running")
            return
        
        # Check if initialization failed
        if self._event_store is None or self._handler_actor is None:
            logger.error(f"Cannot start subscription {self.subscriber_id}: Not properly initialized")
            return
        
        self.running = True
        
        # Load the current position
        self._load_position()
        
        # Enter the polling loop
        logger.info(f"Subscription {self.subscriber_id} started")
        
        try:
            while self.running:
                try:
                    self._tick()
                except Exception as e:
                    logger.error(f"Error in subscription {self.subscriber_id} tick: {str(e)}", exc_info=True)
                    # Continue processing despite errors
                
                # Sleep for the tick interval
                time.sleep(self.tick_interval)
        except Exception as e:
            logger.error(f"Fatal error in subscription {self.subscriber_id}: {str(e)}", exc_info=True)
        
        logger.info(f"Subscription {self.subscriber_id} stopped")
    
    def stop(self) -> None:
        """Stop the subscription polling process."""
        logger.info(f"Stopping subscription {self.subscriber_id}")
        self.running = False
    
    def _load_position(self) -> None:
        """Load the current position from the event store."""
        try:
            # Read the last position message from the position stream
            last_position_message = self._event_store._read_last_message(self.subscriber_stream_name)
            
            if last_position_message:
                self.current_position = last_position_message.get("data", {}).get("position", -1)
                logger.debug(f"Loaded position {self.current_position} for {self.subscriber_id}")
            else:
                self.current_position = -1
                logger.debug(f"No position found for {self.subscriber_id}, starting from beginning")
        except Exception as e:
            logger.error(f"Error loading position for {self.subscriber_id}: {str(e)}")
            self.current_position = -1
    
    def _tick(self) -> None:
        """Process a single tick of the subscription."""
        # Get the next batch of messages
        messages = self._get_next_batch_of_messages()
        
        if not messages:
            return
        
        # Process the batch
        self._process_batch(messages)
    
    def _get_next_batch_of_messages(self) -> List[Message]:
        """Get the next batch of messages from the event store."""
        try:
            raw_messages = self._event_store._read(
                self.stream_category,
                position=self.current_position + 1,
                no_of_messages=self.messages_per_tick,
            )
            
            # Filter messages based on origin stream if needed
            if self.origin_stream:
                raw_messages = [
                    message for message in raw_messages
                    if message.get("metadata", {}).get("origin_stream") == self.origin_stream
                ]
            
            # Convert raw messages to Message objects
            messages = [Message.from_dict(message) for message in raw_messages]
            
            return messages
        except Exception as e:
            logger.error(f"Error fetching messages for {self.subscriber_id}: {str(e)}")
            return []
    
    def _process_batch(self, messages: List[Message]) -> None:
        """Process a batch of messages."""
        logger.debug(f"Processing {len(messages)} messages for {self.subscriber_id}")
        
        for message in messages:
            try:
                # Send message to handler actor for processing
                # Using message.to_dict() for serialization
                ray.get(self._handler_actor.handle_message.remote(message.to_dict()))
                
                # Update position after successful processing
                self._update_position(message.global_position)
                
                logger.debug(f"Processed message {message.id} for {self.subscriber_id}")
            except Exception as e:
                # Log error but continue processing other messages
                logger.error(
                    f"Error processing message {message.id} for {self.subscriber_id}: {str(e)}",
                    exc_info=True
                )
    
    def _update_position(self, position: int) -> None:
        """Update the current position in the event store."""
        self.current_position = position
        self.messages_since_last_position_write += 1
        
        # Write position to stream periodically
        if self.messages_since_last_position_write >= self.position_update_interval:
            try:
                self._event_store._write(
                    self.subscriber_stream_name,
                    "position",
                    {"position": position},
                )
                self.messages_since_last_position_write = 0
                logger.debug(f"Updated position to {position} for {self.subscriber_id}")
            except Exception as e:
                logger.error(f"Error updating position for {self.subscriber_id}: {str(e)}")


@ray.remote
class HandlerActor:
    """Ray actor for handling events and commands.
    
    This actor handles specific events or commands by delegating to the appropriate
    handler methods in the handler class.
    """
    
    def __init__(self, domain_config: Dict, handler_cls_name: str) -> None:
        """Initialize the HandlerActor.
        
        Args:
            domain_config: The domain configuration (simplified serializable version)
            handler_cls_name: Fully qualified name of the handler class
        """
        self.domain_config = domain_config
        self.handler_cls_name = handler_cls_name
        
        # Import the handler class
        try:
            module_name, class_name = self.handler_cls_name.rsplit(".", 1)
            module = importlib.import_module(module_name)
            self.handler_cls = getattr(module, class_name)
            
            # Create the domain and initialize the handler
            self._initialize()
        except Exception as e:
            logger.error(f"Error initializing HandlerActor for {handler_cls_name}: {str(e)}", exc_info=True)
            # Don't raise here - let the actor be created so it can report errors properly
            self.handler_cls = None
            self._handler = None
            self._domain = None
    
    def _initialize(self) -> None:
        """Initialize the handler and domain."""
        try:
            # Import Domain dynamically to avoid circular imports
            from protean.domain import Domain
            
            # Create a domain instance with the configuration
            self._domain = Domain("handler", config=self.domain_config)
            
            # Initialize the domain
            self._domain.init()
            
            # Create the handler instance
            self._handler = self.handler_cls()
            
            # Set up handler context by injecting repositories and other dependencies
            logger.debug(f"Handler {self.handler_cls_name} initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing handler {self.handler_cls_name}: {str(e)}", exc_info=True)
            self._handler = None
            self._domain = None
    
    def handle_message(self, message_dict: Dict) -> Any:
        """Handle a message by delegating to the appropriate handler method.
        
        Args:
            message_dict: The message to handle as a dictionary
        
        Returns:
            The result of handling the message
        """
        # Check if initialization failed
        if self._handler is None:
            logger.error(f"Cannot handle message: Handler {self.handler_cls_name} not initialized")
            return {"error": f"Handler {self.handler_cls_name} not initialized"}
            
        try:
            # Convert dictionary back to Message object
            message = Message.from_dict(message_dict)
            
            # Set up the global context
            g.domain = self._domain
            
            # Check if the handler has a handler method for this message type
            if hasattr(self._handler, f"handle_{message.type}"):
                handler_method = getattr(self._handler, f"handle_{message.type}")
            elif hasattr(self._handler, "__call__"):
                handler_method = self._handler.__call__
            else:
                logger.warning(f"No handler method found for message type {message.type}")
                return None
                
            # Call the handler method
            logger.debug(f"Calling handler method for message {message.id}")
            
            # Pass the serialized data to the handler
            result = handler_method(message)
            
            return result
        except Exception as e:
            logger.error(f"Error handling message: {str(e)}", exc_info=True)
            
            # Try to call the handle_error method if it exists
            if hasattr(self._handler, "handle_error"):
                try:
                    self._handler.handle_error(e, message_dict)
                except Exception as error_handler_error:
                    logger.error(f"Error in handle_error method: {str(error_handler_error)}")
            
            # Return an error result
            return {"error": str(e)}


@ray.remote
class BrokerSubscriptionActor:
    """Ray actor for broker subscriptions.
    
    This actor polls a broker for new messages and processes them.
    """
    
    def __init__(
        self,
        domain_config: Dict,
        broker_name: str,
        subscriber_id: str,
        channel: str,
        handler_cls_name: str,
        messages_per_tick: int = 10,
        tick_interval: float = 1.0,
    ) -> None:
        """Initialize the BrokerSubscriptionActor.
        
        Args:
            domain_config: The domain configuration (simplified serializable version)
            broker_name: Name of the broker to subscribe to
            subscriber_id: Unique identifier for the subscriber
            channel: Channel to subscribe to
            handler_cls_name: Fully qualified name of the handler class
            messages_per_tick: Number of messages to process per tick
            tick_interval: Interval between polling ticks in seconds
        """
        self.domain_config = domain_config
        self.broker_name = broker_name
        self.subscriber_id = subscriber_id
        self.channel = channel
        self.handler_cls_name = handler_cls_name
        self.messages_per_tick = messages_per_tick
        self.tick_interval = tick_interval
        
        # Control flags
        self.running = False
        
        # Import the handler class
        try:
            module_name, class_name = self.handler_cls_name.rsplit(".", 1)
            module = importlib.import_module(module_name)
            self.handler_cls = getattr(module, class_name)
            
            # Initialize connections
            self._initialize()
        except Exception as e:
            logger.error(f"Error initializing BrokerSubscriptionActor for {subscriber_id}: {str(e)}", exc_info=True)
            self.handler_cls = None
            self._broker = None
            self._domain = None
            self._handler_actor = None
    
    def _initialize(self) -> None:
        """Initialize connections to the domain and broker."""
        try:
            # Import Domain dynamically to avoid circular imports
            from protean.domain import Domain
            
            # Create a domain instance with the configuration
            self._domain = Domain("broker_subscription", config=self.domain_config)
            
            # Initialize the domain
            self._domain.init()
            
            # Get the broker
            if self.broker_name not in self._domain.brokers:
                raise ValueError(f"Broker {self.broker_name} not found in domain brokers")
                
            self._broker = self._domain.brokers[self.broker_name]
            
            # Get a reference to the handler actor
            self._handler_actor = ray.get_actor(f"handler_{self.handler_cls_name}")
            
            logger.debug(f"Broker subscription {self.subscriber_id} initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing broker subscription {self.subscriber_id}: {str(e)}", exc_info=True)
            self._broker = None
            self._domain = None
            self._handler_actor = None
    
    def start(self) -> None:
        """Start the subscription polling process."""
        if self.running:
            logger.warning(f"Broker subscription {self.subscriber_id} is already running")
            return
        
        self.running = True
        
        # Enter the polling loop
        logger.info(f"Broker subscription {self.subscriber_id} started")
        
        try:
            while self.running:
                try:
                    self._tick()
                except Exception as e:
                    logger.error(f"Error in broker subscription {self.subscriber_id} tick: {str(e)}", exc_info=True)
                    # Continue processing despite errors
                
                # Sleep for the tick interval
                time.sleep(self.tick_interval)
        except Exception as e:
            logger.error(f"Fatal error in broker subscription {self.subscriber_id}: {str(e)}", exc_info=True)
        
        logger.info(f"Broker subscription {self.subscriber_id} stopped")
    
    def stop(self) -> None:
        """Stop the subscription polling process."""
        logger.info(f"Stopping broker subscription {self.subscriber_id}")
        self.running = False
    
    def _tick(self) -> None:
        """Process a single tick of the subscription."""
        # Get the next batch of messages
        messages = self._get_next_batch_of_messages()
        
        if not messages:
            return
        
        # Process the batch
        self._process_batch(messages)
    
    def _get_next_batch_of_messages(self) -> List[Dict]:
        """Get the next batch of messages from the broker."""
        try:
            return self._broker.read(self.channel, no_of_messages=self.messages_per_tick)
        except Exception as e:
            logger.error(f"Error fetching messages from broker for {self.subscriber_id}: {str(e)}")
            return []
    
    def _process_batch(self, messages: List[Dict]) -> None:
        """Process a batch of messages."""
        logger.debug(f"Processing {len(messages)} broker messages for {self.subscriber_id}")
        
        for message in messages:
            try:
                # Send message to handler actor for processing
                ray.get(self._handler_actor.handle_message.remote(message))
                
                logger.debug(f"Processed broker message for {self.subscriber_id}")
            except Exception as e:
                # Log error but continue processing other messages
                logger.error(
                    f"Error processing broker message for {self.subscriber_id}: {str(e)}",
                    exc_info=True
                ) 