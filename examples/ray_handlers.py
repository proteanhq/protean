"""
Ray Event/Command Handlers Example

This example demonstrates how to use Ray with Protean to create distributed event and command handlers.
It shows a simple implementation that can be scaled across multiple machines.

To run this example:
1. Make sure Ray is installed (it's included with Protean)
2. Run the example: `python ray_handlers.py`
3. For production: `protean server --domain=your_domain --ray-num-cpus=4`
"""

import logging
from uuid import uuid4

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import String, Boolean
from protean.utils.mixins import handle
from protean.utils.globals import current_domain

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Define an Aggregate
class User(BaseAggregate):
    name = String(required=True)
    email = String(required=True)
    active = Boolean(default=False)
    
    # Commands
    @classmethod
    def register(cls, id, name, email):
        user = cls(id=id, name=name, email=email)
        user.raise_event(UserRegistered(id=id, name=name, email=email))
        return user
    
    def activate(self):
        self.active = True
        self.raise_event(UserActivated(id=self.id))
        
    # Event Application
    def apply_user_registered(self, event):
        self.name = event.name
        self.email = event.email
        
    def apply_user_activated(self, event):
        self.active = True


# Define Events
class UserRegistered(BaseEvent):
    name = String(required=True)
    email = String(required=True)


class UserActivated(BaseEvent):
    pass


# Define Commands
class RegisterUser(BaseCommand):
    name = String(required=True)
    email = String(required=True)


class ActivateUser(BaseCommand):
    pass


# Event Handler with error handling
class UserEventHandler(BaseEventHandler):
    @handle(UserRegistered)
    def user_registered(self, event):
        """Handle UserRegistered event."""
        logger.info(f"User registered: {event.name} ({event.email})")
        # In a real application, you might:
        # - Send a welcome email
        # - Create related entities/aggregates
        # - Update read models/views
        
    @handle(UserActivated)
    def user_activated(self, event):
        """Handle UserActivated event."""
        logger.info(f"User activated: {event.id}")
        # In a real application, you might:
        # - Send a confirmation email
        # - Update read models/views
        # - Trigger other business processes
        
    def handle_error(self, exception, message):
        """Custom error handling for this event handler."""
        logger.error(f"Error handling event {message.type} - {message.id}: {str(exception)}")
        # You could add additional error handling logic here, such as:
        # - Send alerts
        # - Record errors in a database
        # - Retry logic for transient errors


# Command Handler
class UserCommandHandler(BaseCommandHandler):
    @handle(RegisterUser)
    def register_user(self, command):
        """Handle RegisterUser command."""
        try:
            user_id = str(uuid4())
            user = User.register(
                id=user_id,
                name=command.name,
                email=command.email
            )
            logger.info(f"User created with ID: {user_id}")
            return user
        except Exception as e:
            logger.error(f"Error registering user: {str(e)}")
            raise  # Re-raise the exception for proper handling
    
    @handle(ActivateUser)
    def activate_user(self, command):
        """Handle ActivateUser command."""
        try:
            # Load the user aggregate
            user_repo = current_domain.repository_for(User)
            user = user_repo.get(command.id)
            
            if not user:
                raise ValueError(f"User with ID {command.id} not found")
                
            # Activate the user
            user.activate()
            
            # Save the user
            user_repo.add(user)
            logger.info(f"User activated: {user.id}")
            return user
        except Exception as e:
            logger.error(f"Error activating user: {str(e)}")
            raise  # Re-raise the exception for proper handling


def run_example():
    """Run a simple example showing the flow of commands and events."""
    from protean.domain import Domain
    from protean.server.engine import Engine
    
    # Create a domain
    domain = Domain("example")
    
    # Register the domain elements
    domain.register(User, is_event_sourced=True)
    domain.register(UserRegistered, part_of=User)
    domain.register(UserActivated, part_of=User)
    domain.register(RegisterUser, part_of=User)
    domain.register(ActivateUser, part_of=User)
    domain.register(UserEventHandler, part_of=User)
    domain.register(UserCommandHandler, part_of=User)
    
    # Configure Ray
    domain.config["ray"] = {
        "init_args": {
            "num_cpus": 2,  # Limit to 2 CPUs for this example
            "include_dashboard": True,
            "dashboard_port": 8265,
        }
    }
    
    # Initialize the domain
    domain.init()
    
    # Process a command to register a user
    user_id = None
    try:
        result = domain.process(
            RegisterUser(name="John Doe", email="john.doe@example.com"),
            asynchronous=False  # Process synchronously for this example
        )
        logger.info(f"Command processed with result: {result}")
        
        # In a real application, you'd get the user ID from the result
        # For this example, we'll create a dummy ID
        user_id = str(uuid4())
        
        # Now activate the user
        domain.process(
            ActivateUser(id=user_id),
            asynchronous=False
        )
    except Exception as e:
        logger.error(f"Error processing command: {str(e)}")
    
    # In a real application, you'd start the engine to process events/commands continuously
    print("\nTo start the Ray engine and process events/commands continuously:")
    print("1. Create a domain and register your elements")
    print("2. Initialize the domain: domain.init()")
    print("3. Create and start the engine:")
    print("   engine = Engine(domain)")
    print("   engine.run()")
    print("\nFor testing, you can use test mode to process events once and shut down:")
    print("   engine = Engine(domain, test_mode=True)")
    print("   engine.run()")
    print("\nOr simply use the CLI: protean server --domain=your_domain --test-mode")


if __name__ == "__main__":
    # Run the example
    run_example() 